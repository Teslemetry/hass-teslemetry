"""Diagnostic dual-source observation logging for Teslemetry vehicles.

HACS-only, 6.1 line only: never rides an upstream home-assistant/core PR.

For each BLE-paired vehicle this subscribes to both the local VCSEC Bluetooth
broadcast path and the fleet telemetry streaming path for the same fields, and
emits one DEBUG log per state transition on either source. Fields are written as
logfmt key=value pairs in the message body (not ``extra=``, which the ClickStack
shipper drops) so the two sources can be paired after the fact - by vehicle,
field and transition - to compare when each reports the same physical event.
DEBUG is deliberate: it is the one level that does not double-ship across the two
OTel service names. See AGENTS.md ("HACS-only patches that ride main").
"""

from collections.abc import Callable
import logging
from typing import TYPE_CHECKING, Any

from tesla_fleet_api.tesla.vehicle.bluetooth import VehicleBluetooth

# pylint: disable-next=no-name-in-module
from tesla_fleet_api.tesla.vehicle.proto.vcsec_pb2 import (
    ClosureState_E,
    VehicleLockState_E,
)
from teslemetry_stream import TeslemetryStream, TeslemetryStreamVehicle
from teslemetry_stream.const import Signal

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from . import TeslemetryConfigEntry

_LOGGER = logging.getLogger(__name__)

# Canonical field names both sources map to; the shared (vin, field) scope is
# what makes an opposite-source pair recognisable.
FIELD_LOCKED = "Locked"
FIELD_CHARGE_PORT = "ChargePortDoorOpen"
FIELD_TRUNK_FRONT = "DoorState.TrunkFront"

_LOCKED_STATES = (
    VehicleLockState_E.VEHICLELOCKSTATE_LOCKED,
    VehicleLockState_E.VEHICLELOCKSTATE_INTERNAL_LOCKED,
)
_UNLOCKED_STATES = (
    VehicleLockState_E.VEHICLELOCKSTATE_UNLOCKED,
    VehicleLockState_E.VEHICLELOCKSTATE_SELECTIVE_UNLOCKED,
)


def _ble_locked(value: int) -> bool | None:
    """Map the VCSEC lock enum to locked/unlocked, matching the lock entity."""
    if value in _LOCKED_STATES:
        return True
    if value in _UNLOCKED_STATES:
        return False
    return None


def _ble_open(value: int) -> bool | None:
    """Map a VCSEC closure enum to open/closed, matching the cover entities."""
    if value in (
        ClosureState_E.CLOSURESTATE_UNKNOWN,
        ClosureState_E.CLOSURESTATE_FAILED_UNLATCH,
    ):
        return None
    return value != ClosureState_E.CLOSURESTATE_CLOSED


def _stream_bool(value: Any) -> bool | None:
    """Normalise a streamed value to a bool, or None when unrecognised."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return None


def _stream_trunk_front(door_state: Any) -> bool | None:
    """Extract the front-trunk open state from a streamed DoorState map."""
    if isinstance(door_state, dict):
        return _stream_bool(door_state.get("TrunkFront"))
    return None


def _createdat_to_ms(created_at: Any) -> int | None:
    """Parse a stream event's ISO ``createdAt`` into epoch milliseconds."""
    if not isinstance(created_at, str):
        return None
    parsed = dt_util.parse_datetime(created_at)
    if parsed is None:
        return None
    return int(parsed.timestamp() * 1000)


def _token(value: bool | int | None) -> str:
    """Render one logfmt value: booleans lowercase, None as ``none``."""
    if value is None:
        return "none"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


# Streamed fields: (signal to enable and filter on, canonical field, extractor).
_STREAM_FIELDS: tuple[
    tuple[Signal, str, Callable[[dict[str, Any]], bool | None]], ...
] = (
    (Signal.LOCKED, FIELD_LOCKED, lambda data: _stream_bool(data.get(Signal.LOCKED))),
    (
        Signal.CHARGE_PORT_DOOR_OPEN,
        FIELD_CHARGE_PORT,
        lambda data: _stream_bool(data.get(Signal.CHARGE_PORT_DOOR_OPEN)),
    ),
    (
        Signal.DOOR_STATE,
        FIELD_TRUNK_FRONT,
        lambda data: _stream_trunk_front(data.get(Signal.DOOR_STATE)),
    ),
)


class _VehicleObservationLogger:
    """Track last value per source and field, logging only transitions."""

    def __init__(self, vin: str) -> None:
        """Initialize for one vehicle."""
        self.vin = vin
        self._last: dict[tuple[str, str], bool | None] = {}

    @callback
    def record(
        self, source: str, field: str, value: bool | None, observed_at: int | None
    ) -> None:
        """Log a source's report of a field, but only when the value changed.

        ``observed_at`` is the source-side event time in epoch milliseconds, or
        None when the source carries no timestamp (the VCSEC BLE broadcast). It
        renders as ``observed_at=none`` so the key stays present on every line.
        """
        key = (source, field)
        previous = self._last.get(key)
        if previous == value:
            return
        self._last[key] = value
        _LOGGER.debug(
            "event=observation source=%s field=%s prev=%s new=%s"
            " observed_at=%s received_at=%s vehicle=%s",
            source,
            field,
            _token(previous),
            _token(value),
            _token(observed_at),
            int(dt_util.utcnow().timestamp() * 1000),
            self.vin,
        )


def _make_stream_handler(
    logger: _VehicleObservationLogger,
    field: str,
    extract: Callable[[dict[str, Any]], bool | None],
) -> Callable[[dict[str, Any]], None]:
    """Build a raw-stream listener that records one field's transitions."""

    @callback
    def handle(event: dict[str, Any]) -> None:
        logger.record(
            "stream",
            field,
            extract(event["data"]),
            _createdat_to_ms(event.get("createdAt")),
        )

    return handle


@callback
def async_setup_observation_log(
    entry: TeslemetryConfigEntry,
    hass: HomeAssistant,
    bluetooth: VehicleBluetooth,
    stream: TeslemetryStream,
    stream_vehicle: TeslemetryStreamVehicle,
    vin: str,
) -> None:
    """Wire both observation sources for one BLE-paired vehicle.

    Every subscription is torn down on unload. The streamed fields are enabled
    directly so streaming reports arrive even when no streaming entity for the
    field exists, which is the case once a vehicle is BLE paired.
    """
    logger = _VehicleObservationLogger(vin)

    # BLE broadcast path: VCSEC VehicleStatus carries no source-side timestamp,
    # so observed_at is None and only received_at is available here.
    entry.async_on_unload(
        bluetooth.listen_vehicle_lock_state(
            lambda value: logger.record("ble", FIELD_LOCKED, _ble_locked(value), None)
        )
    )
    entry.async_on_unload(
        bluetooth.listen_charge_port(
            lambda value: logger.record(
                "ble", FIELD_CHARGE_PORT, _ble_open(value), None
            )
        )
    )
    entry.async_on_unload(
        bluetooth.listen_front_trunk(
            lambda value: logger.record(
                "ble", FIELD_TRUNK_FRONT, _ble_open(value), None
            )
        )
    )

    # Streaming path: subscribe raw so the event's createdAt survives as the
    # source-side observed_at, and enable each field server-side.
    for signal, field, extract in _STREAM_FIELDS:
        entry.async_create_background_task(
            hass,
            stream_vehicle.add_field(signal),
            f"teslemetry_observation_log_{vin}_{signal}",
        )
        entry.async_on_unload(
            stream.async_add_listener(
                _make_stream_handler(logger, field, extract),
                {"vin": vin, "data": {signal: None}},
            )
        )
