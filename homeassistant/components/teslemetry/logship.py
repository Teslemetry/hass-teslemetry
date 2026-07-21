"""Opt-in ClickStack log shipping for the Teslemetry HACS integration.

HACS-only: this module must never ride an upstream home-assistant/core PR.
It ships debug logs from this integration and its two support libraries to
Teslemetry's ClickStack so command/connection issues can be diagnosed
without users pasting log files.
"""

import asyncio
from collections import deque
import logging
from typing import Any, override
from weakref import WeakKeyDictionary

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import instance_id
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .const import DOMAIN

OTLP_ENDPOINT = "https://clickstack.teslemetry.com/v1/logs"

# Config-entry option key for the durable, DEBUG-independent shipping opt-in.
CONF_SHIP_LOGS_TO_CLICKSTACK = "ship_logs_to_clickstack"

# Shared public ingestion key, already shipped in the Teslemetry web app's
# browser bundle. Not a per-user secret: ClickStack ingest checks it by
# string equality only, so reusing it needs no server-side change.
INGEST_KEY = "8f40841f-391a-4bfd-970a-b33f5fe0c2e1"

# Privacy hard line: only these three loggers are ever attached to. Never
# root, never other integrations, never HA system logs.
SHIPPED_LOGGERS = (
    "homeassistant.components.teslemetry",
    "tesla_fleet_api",
    "teslemetry_stream",
)

# Debug-log gate: one of two ways shipping gets authorized (the other is the
# durable per-entry option tracked by TeslemetryLogShipper._force_count).
# Scoped to the integration's own logger, even for records coming from the
# two library loggers.
_GATE_LOGGER_NAME = "homeassistant.components.teslemetry"
_INTERNAL_LOGGER_NAME = __name__

# This module's own diagnostics logger. _OTLPLogHandler.emit excludes it by
# name, so its warnings never get shipped or feed back into the buffer.
_LOGGER = logging.getLogger(_INTERNAL_LOGGER_NAME)

MAX_BUFFER_SIZE = 1000
BATCH_SIZE = 200
FLUSH_INTERVAL = 5.0
HTTP_TIMEOUT = 10.0

_SEVERITY_NUMBERS = {
    logging.DEBUG: 5,
    logging.INFO: 9,
    logging.WARNING: 13,
    logging.ERROR: 17,
    logging.CRITICAL: 21,
}


def _severity_number(levelno: int) -> int:
    """Map a stdlib log level to an OTLP severity number."""
    number = 1
    for level, value in _SEVERITY_NUMBERS.items():
        if levelno >= level:
            number = value
    return number


def _format_record(record: logging.LogRecord) -> str:
    """Render a record's message with any exception folded in."""
    return logging.Formatter().format(record)


def _attr(key: str, value: Any) -> dict[str, Any]:
    """Build an OTLP AnyValue-typed attribute entry."""
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _record_to_log_record(record: logging.LogRecord) -> dict[str, Any]:
    """Convert a stdlib LogRecord to an OTLP LogRecord."""
    return {
        "timeUnixNano": str(int(record.created * 1e9)),
        "severityNumber": _severity_number(record.levelno),
        "severityText": record.levelname,
        "body": {"stringValue": _format_record(record)},
        "attributes": [
            _attr("logger.name", record.name),
            _attr("code.function", record.funcName),
            _attr("code.lineno", record.lineno),
        ],
    }


def build_payload(
    records: list[logging.LogRecord], resource_attrs: dict[str, Any]
) -> dict[str, Any]:
    """Build an OTLP/HTTP JSON ExportLogsServiceRequest for a batch."""
    scopes: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        scopes.setdefault(record.name, []).append(_record_to_log_record(record))

    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [_attr(k, v) for k, v in resource_attrs.items()]
                },
                "scopeLogs": [
                    {"scope": {"name": name}, "logRecords": log_records}
                    for name, log_records in scopes.items()
                ],
            }
        ]
    }


class _OTLPLogHandler(logging.Handler):
    """Buffer records from the watched loggers, bounded and gated."""

    def __init__(
        self, buffer: deque[logging.LogRecord], shipper: TeslemetryLogShipper
    ) -> None:
        """Initialize the handler around a shared bounded buffer."""
        super().__init__(level=logging.DEBUG)
        self._buffer = buffer
        self._shipper = shipper

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """Buffer a record, or drop it if not opted in."""
        # Feedback-loop guard: never ship the shipper's own log records.
        if record.name == _INTERNAL_LOGGER_NAME:
            return
        if not self._shipper.is_shipping_authorized():
            return
        self._buffer.append(record)  # bounded deque drops the oldest when full


class TeslemetryLogShipper:
    """Background OTLP log exporter, shared across config entries."""

    def __init__(self, hass: HomeAssistant, uid: str) -> None:
        """Initialize the shipper for a given account uid."""
        self.hass = hass
        self.uid = uid
        self._refcount = 0
        # Count of currently-acquired entries with the durable opt-in on.
        # >0 authorizes shipping independent of the live DEBUG level, so
        # toggling the option (which reloads the entry) or a full HA restart
        # never silently closes the gate for an opted-in user.
        self._force_count = 0
        self._attached = False
        self._buffer: deque[logging.LogRecord] = deque(maxlen=MAX_BUFFER_SIZE)
        self._handler = _OTLPLogHandler(self._buffer, self)
        self._resource_attrs: dict[str, Any] = {}
        self._task: asyncio.Task | None = None

    def is_shipping_authorized(self) -> bool:
        """Return whether any authorization source currently permits shipping."""
        return self._force_count > 0 or logging.getLogger(
            _GATE_LOGGER_NAME
        ).isEnabledFor(logging.DEBUG)

    async def async_acquire(self, *, force: bool = False) -> None:
        """Attach handlers and start the export loop on first use.

        Refcount only increments once attach succeeds, so a failed attach
        stays retryable on the next acquire instead of poisoning the singleton.
        `force` tracks the durable per-entry opt-in separately from refcount,
        so it must never be applied unless the attach (if needed) succeeded.
        """
        if not self._attached:
            try:
                self._resource_attrs = await self._async_build_resource_attrs()
            except Exception:
                _LOGGER.warning(
                    "ClickStack log shipping failed to start, will retry on next setup"
                )
                raise
            for name in SHIPPED_LOGGERS:
                logging.getLogger(name).addHandler(self._handler)
            self._task = self.hass.async_create_background_task(
                self._async_export_loop(), "teslemetry_logship"
            )
            self._task.add_done_callback(self._on_export_task_done)
            self._attached = True
        self._refcount += 1
        if force:
            self._force_count += 1

    def async_release(self, *, force: bool = False) -> None:
        """Detach handlers and stop the export loop once unused."""
        self._refcount -= 1
        if force:
            self._force_count -= 1
        if self._refcount > 0:
            return
        for name in SHIPPED_LOGGERS:
            logging.getLogger(name).removeHandler(self._handler)
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._attached = False
        self._force_count = 0
        _shippers.pop(self.hass, None)

    def _on_export_task_done(self, task: asyncio.Task) -> None:
        """Warn if the export loop stopped without being released."""
        if task.cancelled() or (exc := task.exception()) is None:
            return
        _LOGGER.warning("ClickStack log shipping stopped unexpectedly: %s", exc)

    async def _async_build_resource_attrs(self) -> dict[str, Any]:
        """Collect resource attributes shipped with every batch."""
        integration = await async_get_integration(self.hass, DOMAIN)
        return {
            "service.name": "hacs-teslemetry",
            "service.version": integration.version or "unknown",
            "deployment.environment.name": "production",
            "homeassistant.version": HA_VERSION,
            "service.instance.id": await instance_id.async_get(self.hass),
            "user.id": self.uid,
            "userId": self.uid,
        }

    async def _async_export_loop(self) -> None:
        """Flush buffered records on a fixed interval until cancelled."""
        while True:
            await asyncio.sleep(FLUSH_INTERVAL)
            await self._async_flush()

    async def _async_flush(self) -> None:
        """Ship one batch. Never raises: shipping must not break the integration."""
        if not self._buffer:
            return
        batch = [
            self._buffer.popleft() for _ in range(min(BATCH_SIZE, len(self._buffer)))
        ]
        try:
            payload = build_payload(batch, self._resource_attrs)
            session = async_get_clientsession(self.hass)
            async with asyncio.timeout(HTTP_TIMEOUT):
                await session.post(
                    OTLP_ENDPOINT,
                    json=payload,
                    headers={"authorization": INGEST_KEY},
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  # fail-silent by design
            return


# Shared across every config entry of this domain, keyed by hass instance
# rather than hass.data[DOMAIN] since it isn't per-entry state.
_shippers: WeakKeyDictionary[HomeAssistant, TeslemetryLogShipper] = WeakKeyDictionary()


def async_get_or_create_logship(hass: HomeAssistant, uid: str) -> TeslemetryLogShipper:
    """Get the hass-wide shipper, creating it attributed to the first uid seen."""
    shipper = _shippers.get(hass)
    if shipper is None:
        shipper = TeslemetryLogShipper(hass, uid)
        _shippers[hass] = shipper
    return shipper


def get_logship(hass: HomeAssistant) -> TeslemetryLogShipper | None:
    """Return the hass-wide shipper if one is currently active."""
    return _shippers.get(hass)
