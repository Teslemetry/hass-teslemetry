"""Test the opt-in ClickStack log shipping (HACS-only)."""

from collections.abc import AsyncGenerator
import logging
from unittest.mock import patch

from aiohttp import ClientConnectionError
import pytest

from homeassistant.components.teslemetry.const import DOMAIN
from homeassistant.components.teslemetry.logship import (
    INGEST_KEY,
    OTLP_ENDPOINT,
    TeslemetryLogShipper,
    _severity_number,
    build_payload,
    get_logship,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from . import mock_config_entry, reload_platform, setup_platform
from .const import UNIQUE_ID

from tests.common import MockConfigEntry
from tests.test_util.aiohttp import AiohttpClientMocker

COMPONENT_LOGGER = "homeassistant.components.teslemetry"
LIBRARY_LOGGER = "tesla_fleet_api"


@pytest.fixture
async def shipper(hass: HomeAssistant) -> AsyncGenerator[TeslemetryLogShipper]:
    """Create and fully tear down a standalone, opted-in log shipper."""
    log_shipper = TeslemetryLogShipper(hass, UNIQUE_ID)
    await log_shipper.async_acquire(force=True)
    try:
        yield log_shipper
    finally:
        log_shipper.async_release(force=True)


async def test_no_opt_in_nothing_ships(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Without the opt-in, nothing ships no matter the log level or logger."""
    caplog.set_level(logging.DEBUG, logger=COMPONENT_LOGGER)
    caplog.set_level(logging.DEBUG, logger=LIBRARY_LOGGER)
    log_shipper = TeslemetryLogShipper(hass, UNIQUE_ID)
    await log_shipper.async_acquire()
    try:
        logging.getLogger(COMPONENT_LOGGER).debug("should not ship")
        logging.getLogger(LIBRARY_LOGGER).debug("should not ship either")
        assert len(log_shipper._buffer) == 0
    finally:
        log_shipper.async_release()


async def test_self_skip_avoids_feedback_loop(
    hass: HomeAssistant,
    shipper: TeslemetryLogShipper,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The shipper's own log records are never buffered."""
    caplog.set_level(logging.DEBUG, logger=COMPONENT_LOGGER)
    logging.getLogger(f"{COMPONENT_LOGGER}.logship").debug("internal shipper message")
    assert len(shipper._buffer) == 0

    logging.getLogger(COMPONENT_LOGGER).debug("a real message")
    assert len(shipper._buffer) == 1


async def test_bounded_buffer_drops_oldest(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The buffer is capped; the oldest records are dropped once full."""
    caplog.set_level(logging.DEBUG, logger=COMPONENT_LOGGER)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "homeassistant.components.teslemetry.logship.MAX_BUFFER_SIZE", 5
        )
        log_shipper = TeslemetryLogShipper(hass, UNIQUE_ID)
        await log_shipper.async_acquire(force=True)
        try:
            component_logger = logging.getLogger(COMPONENT_LOGGER)
            for i in range(8):
                component_logger.debug("message %s", i)

            assert len(log_shipper._buffer) == 5
            messages = [record.getMessage() for record in log_shipper._buffer]
            assert messages == [f"message {i}" for i in range(3, 8)]
        finally:
            log_shipper.async_release(force=True)


async def test_exception_folding(
    hass: HomeAssistant,
    shipper: TeslemetryLogShipper,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exception info is folded into the shipped record's body."""
    caplog.set_level(logging.DEBUG, logger=COMPONENT_LOGGER)

    def _raise() -> None:
        raise ValueError("boom")

    try:
        _raise()
    except ValueError:
        logging.getLogger(COMPONENT_LOGGER).exception("it failed")

    assert len(shipper._buffer) == 1
    payload = build_payload(list(shipper._buffer), {})
    body = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"][
        "stringValue"
    ]
    assert "it failed" in body
    assert "ValueError: boom" in body
    assert "Traceback" in body


def test_severity_number_mapping() -> None:
    """Stdlib levels map to the OTLP severity number ranges."""
    assert _severity_number(logging.DEBUG) == 5
    assert _severity_number(logging.INFO) == 9
    assert _severity_number(logging.WARNING) == 13
    assert _severity_number(logging.ERROR) == 17
    assert _severity_number(logging.CRITICAL) == 21


def test_build_payload_shape() -> None:
    """The OTLP payload groups records by logger under one resource."""
    record = logging.LogRecord(
        name=COMPONENT_LOGGER,
        level=logging.DEBUG,
        pathname=__file__,
        lineno=42,
        msg="hello %s",
        args=("world",),
        exc_info=None,
        func="test_func",
    )
    resource_attrs = {
        "service.name": "hacs-teslemetry",
        "user.id": UNIQUE_ID,
    }
    payload = build_payload([record], resource_attrs)

    resource_logs = payload["resourceLogs"][0]
    attrs = {a["key"]: a["value"] for a in resource_logs["resource"]["attributes"]}
    assert attrs["service.name"] == {"stringValue": "hacs-teslemetry"}
    assert attrs["user.id"] == {"stringValue": UNIQUE_ID}

    scope_logs = resource_logs["scopeLogs"]
    assert len(scope_logs) == 1
    assert scope_logs[0]["scope"]["name"] == COMPONENT_LOGGER

    log_record = scope_logs[0]["logRecords"][0]
    assert log_record["severityNumber"] == 5
    assert log_record["severityText"] == "DEBUG"
    assert log_record["body"]["stringValue"] == "hello world"
    record_attrs = {a["key"]: a["value"] for a in log_record["attributes"]}
    assert record_attrs["logger.name"] == {"stringValue": COMPONENT_LOGGER}
    assert record_attrs["code.function"] == {"stringValue": "test_func"}
    assert record_attrs["code.lineno"] == {"intValue": "42"}


async def test_flush_posts_correct_request(
    hass: HomeAssistant,
    shipper: TeslemetryLogShipper,
    caplog: pytest.LogCaptureFixture,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A flush ships a batch as an authenticated OTLP POST."""
    aioclient_mock.post(OTLP_ENDPOINT, json={})
    caplog.set_level(logging.DEBUG, logger=COMPONENT_LOGGER)
    logging.getLogger(COMPONENT_LOGGER).debug("shipped message")

    await shipper._async_flush()

    assert aioclient_mock.call_count == 1
    _method, url, data, headers = aioclient_mock.mock_calls[0]
    assert str(url) == OTLP_ENDPOINT
    assert headers["authorization"] == INGEST_KEY

    log_record = data["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    assert log_record["body"]["stringValue"] == "shipped message"
    resource_attrs = {
        a["key"]: a["value"] for a in data["resourceLogs"][0]["resource"]["attributes"]
    }
    assert resource_attrs["user.id"] == {"stringValue": UNIQUE_ID}
    assert len(shipper._buffer) == 0


async def test_flush_fails_silently_on_connection_error(
    hass: HomeAssistant,
    shipper: TeslemetryLogShipper,
    caplog: pytest.LogCaptureFixture,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A network failure during export never raises; the batch is dropped."""
    aioclient_mock.post(OTLP_ENDPOINT, exc=ClientConnectionError())
    caplog.set_level(logging.DEBUG, logger=COMPONENT_LOGGER)
    logging.getLogger(COMPONENT_LOGGER).debug("will fail to ship")

    await shipper._async_flush()  # must not raise

    assert len(shipper._buffer) == 0


async def test_attach_detach_refcounting(hass: HomeAssistant) -> None:
    """Handlers stay attached until every acquirer has released."""
    log_shipper = TeslemetryLogShipper(hass, UNIQUE_ID)

    await log_shipper.async_acquire()
    assert log_shipper._handler in logging.getLogger(LIBRARY_LOGGER).handlers

    # A second config entry acquiring the same shared shipper.
    await log_shipper.async_acquire()
    log_shipper.async_release()
    assert log_shipper._handler in logging.getLogger(LIBRARY_LOGGER).handlers

    log_shipper.async_release()
    assert log_shipper._handler not in logging.getLogger(LIBRARY_LOGGER).handlers
    assert log_shipper._task is None


async def test_reload_reattaches_handler_and_export_task(
    hass: HomeAssistant,
) -> None:
    """A config-entry reload must re-attach the handler and restart export."""
    entry = await setup_platform(hass)

    first_shipper = get_logship(hass)
    assert first_shipper is not None
    assert first_shipper._handler in logging.getLogger(LIBRARY_LOGGER).handlers
    assert first_shipper._task is not None
    assert not first_shipper._task.done()

    await reload_platform(hass, entry)

    second_shipper = get_logship(hass)
    assert second_shipper is not None
    assert second_shipper._handler in logging.getLogger(LIBRARY_LOGGER).handlers
    assert second_shipper._task is not None
    assert not second_shipper._task.done()


async def test_opt_in_ships(
    hass: HomeAssistant,
    shipper: TeslemetryLogShipper,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The durable opt-in is the sole trigger authorizing shipping."""
    caplog.set_level(logging.INFO, logger=COMPONENT_LOGGER)
    logging.getLogger(COMPONENT_LOGGER).info("should ship via opt-in")
    assert len(shipper._buffer) == 1


async def test_opt_in_survives_reload(hass: HomeAssistant) -> None:
    """The durable opt-in stays authorized across a config-entry reload.

    A real HA restart just re-runs setup with the persisted option, so a
    reload is the closest faithful proxy available in a test.
    """
    entry = await setup_platform(hass, [], options={"ship_logs_to_clickstack": True})

    shipper = get_logship(hass)
    assert shipper is not None
    assert shipper.is_shipping_authorized()

    await reload_platform(hass, entry, [])

    shipper = get_logship(hass)
    assert shipper is not None
    assert shipper.is_shipping_authorized()


async def test_acquire_failure_warns_and_does_not_poison_refcount(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed attach warns visibly and leaves the shipper retryable."""
    log_shipper = TeslemetryLogShipper(hass, UNIQUE_ID)
    caplog.set_level(logging.WARNING, logger=f"{COMPONENT_LOGGER}.logship")

    with (
        patch.object(
            log_shipper,
            "_async_build_resource_attrs",
            side_effect=RuntimeError("transient failure"),
        ),
        pytest.raises(RuntimeError),
    ):
        await log_shipper.async_acquire()

    assert "ClickStack log shipping failed to start" in caplog.text
    assert log_shipper._refcount == 0
    assert not log_shipper._attached
    assert log_shipper._handler not in logging.getLogger(LIBRARY_LOGGER).handlers

    await log_shipper.async_acquire()
    try:
        assert log_shipper._handler in logging.getLogger(LIBRARY_LOGGER).handlers
        assert log_shipper._task is not None
    finally:
        log_shipper.async_release()


async def test_export_task_death_warns(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An export loop that dies unexpectedly warns instead of going silent."""
    log_shipper = TeslemetryLogShipper(hass, UNIQUE_ID)
    caplog.set_level(logging.WARNING, logger=f"{COMPONENT_LOGGER}.logship")

    with (
        pytest.MonkeyPatch.context() as monkeypatch,
        patch.object(log_shipper, "_async_flush", side_effect=RuntimeError("loop bug")),
    ):
        monkeypatch.setattr(
            "homeassistant.components.teslemetry.logship.FLUSH_INTERVAL", 0
        )
        await log_shipper.async_acquire()
        try:
            with pytest.raises(RuntimeError):
                await log_shipper._task
        finally:
            log_shipper._task = None
            log_shipper.async_release()

    assert "ClickStack log shipping stopped unexpectedly" in caplog.text


async def test_transient_acquire_failure_then_reload_reattaches(
    hass: HomeAssistant,
) -> None:
    """A one-time acquire failure must not permanently poison the shipper."""
    original = TeslemetryLogShipper._async_build_resource_attrs
    call_count = 0

    async def flaky(self):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient failure")
        return await original(self)

    with patch.object(TeslemetryLogShipper, "_async_build_resource_attrs", flaky):
        entry = mock_config_entry()
        entry.add_to_hass(hass)
        first_result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        reload_result = await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert first_result is False
    assert reload_result is True
    shipper = get_logship(hass)
    assert shipper is not None
    assert shipper._handler in logging.getLogger(LIBRARY_LOGGER).handlers
    assert shipper._task is not None
    assert not shipper._task.done()


async def test_setup_entry_shares_singleton_across_entries(
    hass: HomeAssistant,
) -> None:
    """Two config entries share one shipper, attributed to the first uid."""
    entry_one = mock_config_entry()
    entry_two = MockConfigEntry(
        domain=DOMAIN,
        entry_id="second_account_entry",
        version=2,
        unique_id="second-account-uid",
        data=dict(entry_one.data),
    )

    entry_one.add_to_hass(hass)
    entry_two.add_to_hass(hass)

    # Setting up the domain's first entry also sets up any other pending
    # entries for that domain, so both load from this single call.
    await hass.config_entries.async_setup(entry_one.entry_id)
    await hass.async_block_till_done()

    assert entry_one.state is ConfigEntryState.LOADED
    assert entry_two.state is ConfigEntryState.LOADED

    log_shipper = get_logship(hass)
    assert log_shipper is not None
    assert log_shipper.uid == UNIQUE_ID
    assert log_shipper._handler in logging.getLogger(LIBRARY_LOGGER).handlers

    await hass.config_entries.async_unload(entry_one.entry_id)
    await hass.async_block_till_done()
    assert get_logship(hass) is log_shipper
    assert log_shipper._handler in logging.getLogger(LIBRARY_LOGGER).handlers

    await hass.config_entries.async_unload(entry_two.entry_id)
    await hass.async_block_till_done()
    assert get_logship(hass) is None
    assert log_shipper._handler not in logging.getLogger(LIBRARY_LOGGER).handlers
