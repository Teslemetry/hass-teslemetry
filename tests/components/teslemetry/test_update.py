"""Test the Teslemetry update platform."""

import copy
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion
from teslemetry_stream import Signal

from homeassistant.components.teslemetry.coordinator import VEHICLE_INTERVAL
from homeassistant.components.teslemetry.update import (
    ATTR_DOWNLOAD_PERCENTAGE,
    ATTR_INSTALL_PERCENTAGE,
    ATTR_SCHEDULED_AT,
    INSTALLING,
    SCHEDULED_STALE_AFTER,
)
from homeassistant.components.update import DOMAIN as UPDATE_DOMAIN, SERVICE_INSTALL
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON, Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.restore_state import STORAGE_KEY as RESTORE_STATE_KEY
from homeassistant.util import dt as dt_util

from . import assert_entities, reload_platform, setup_platform
from .const import COMMAND_OK, VEHICLE_DATA, VEHICLE_DATA_ALT

from tests.common import (
    async_fire_time_changed,
    async_mock_restore_state_shutdown_restart,
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
)


async def test_update(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the update entities are correct."""

    entry = await setup_platform(hass, [Platform.UPDATE])
    assert_entities(hass, entry.entry_id, entity_registry, snapshot)


async def test_update_alt(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_vehicle_data: AsyncMock,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the update entities are correct."""

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    entry = await setup_platform(hass, [Platform.UPDATE])
    assert_entities(hass, entry.entry_id, entity_registry, snapshot)


async def test_update_services(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the update services work."""

    await setup_platform(hass, [Platform.UPDATE])

    entity_id = "update.test_update"

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.schedule_software_update",
        return_value=COMMAND_OK,
    ) as call:
        await hass.services.async_call(
            UPDATE_DOMAIN,
            SERVICE_INSTALL,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        call.assert_called_once()

    VEHICLE_INSTALLING = copy.deepcopy(VEHICLE_DATA)
    VEHICLE_INSTALLING["response"]["vehicle_state"]["software_update"]["status"] = (
        INSTALLING
    )
    mock_vehicle_data.return_value = VEHICLE_INSTALLING
    freezer.tick(VEHICLE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes["in_progress"] == 1


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_update_streaming(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
) -> None:
    """Tests that the select entities with streaming are correct."""

    entry = await setup_platform(hass, [Platform.UPDATE])

    # Stream update
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 50,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: None,
                Signal.SOFTWARE_UPDATE_VERSION: "2025.2.1",
                Signal.VERSION: "2025.1.1",
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    state = hass.states.get("update.test_update")
    assert state.attributes["in_progress"] is True
    assert state.attributes["update_percentage"] == 50
    assert state == snapshot(name="downloading")

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 100,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: 1,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: None,
                Signal.SOFTWARE_UPDATE_VERSION: "2025.2.1",
                Signal.VERSION: "2025.1.1",
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()
    state = hass.states.get("update.test_update")
    # Install percentages up to 10% reflect Tesla's pre-installation step, not real progress
    assert state.attributes["in_progress"] is False
    assert state.attributes["update_percentage"] is None
    assert state == snapshot(name="ready")

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 100,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: 50,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: None,
                Signal.SOFTWARE_UPDATE_VERSION: "2025.2.1",
                Signal.VERSION: "2025.1.1",
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()
    state = hass.states.get("update.test_update")
    assert state.attributes["in_progress"] is True
    assert state.attributes["update_percentage"] == 50
    assert state == snapshot(name="installing")

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 100,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: 100,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: None,
                Signal.SOFTWARE_UPDATE_VERSION: "2025.2.1",
                Signal.VERSION: "2025.1.1",
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()
    state = hass.states.get("update.test_update")
    # 100% installed is complete, not in progress
    assert state.attributes["in_progress"] is False
    assert state.attributes["update_percentage"] is None
    assert state == snapshot(name="install_complete")

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: None,
                Signal.SOFTWARE_UPDATE_VERSION: "",
                Signal.VERSION: "2025.2.1",
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()
    state = hass.states.get("update.test_update")
    assert state.attributes["in_progress"] is False
    assert state.attributes["update_percentage"] is None
    assert state == snapshot(name="updated")

    await reload_platform(hass, entry, [Platform.UPDATE])

    state = hass.states.get("update.test_update")
    assert state.attributes["in_progress"] is False
    assert state.attributes["update_percentage"] is None
    assert state == snapshot(name="restored")


async def test_update_streaming_scheduled_not_clobbered(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
) -> None:
    """Test that a scheduled install stays in progress until real progress or cancellation."""

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    await setup_platform(hass, [Platform.UPDATE])

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: 1735689600,
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()
    state = hass.states.get("update.test_update")
    assert state.attributes["in_progress"] is True
    assert state.attributes["update_percentage"] is None
    assert state == snapshot(name="scheduled")

    # Download begins and the schedule clears in the same payload: progress must win
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 5,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: None,
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()
    state = hass.states.get("update.test_update")
    assert state.attributes["in_progress"] is True
    assert state.attributes["update_percentage"] == 5
    assert state == snapshot(name="downloading_after_schedule_cleared")


@pytest.mark.parametrize(
    ("percentages", "elapsed", "in_progress"),
    [
        pytest.param(
            {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: None,
            },
            SCHEDULED_STALE_AFTER + timedelta(seconds=1),
            False,
            id="expired",
        ),
        pytest.param(
            {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: None,
            },
            SCHEDULED_STALE_AFTER - timedelta(minutes=1),
            True,
            id="not_yet_stale",
        ),
        pytest.param(
            {},
            SCHEDULED_STALE_AFTER + timedelta(seconds=1),
            False,
            id="expired_before_any_percentage",
        ),
    ],
)
async def test_update_streaming_scheduled_expiry(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
    freezer: FrozenDateTimeFactory,
    percentages: dict[Signal, None],
    elapsed: timedelta,
    in_progress: bool,
) -> None:
    """Test a scheduled install self-clears only once stale, with no clearing push."""

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    await setup_platform(hass, [Platform.UPDATE])

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                **percentages,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: 1735689600,
                Signal.SOFTWARE_UPDATE_VERSION: "2025.2.1",
                Signal.VERSION: "2025.1.1",
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()
    state = hass.states.get("update.test_update")
    assert state.attributes["in_progress"] is True

    freezer.tick(elapsed)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get("update.test_update")
    assert state.attributes["in_progress"] is in_progress
    assert state.attributes["update_percentage"] is None


async def test_update_streaming_scheduled_expiry_restarts(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a repeated schedule push restarts the staleness window."""

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    await setup_platform(hass, [Platform.UPDATE])

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: 1735689600,
                Signal.SOFTWARE_UPDATE_VERSION: "2025.2.1",
                Signal.VERSION: "2025.1.1",
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    freezer.tick(timedelta(days=1))
    async_fire_time_changed(hass)
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: 1735776000},
            "createdAt": "2024-10-05T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    # Past the first push's deadline, inside the second's.
    freezer.tick(timedelta(days=1, minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    state = hass.states.get("update.test_update")
    assert state.attributes["in_progress"] is True

    freezer.tick(timedelta(days=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    state = hass.states.get("update.test_update")
    assert state.attributes["in_progress"] is False
    assert state.attributes["update_percentage"] is None


async def test_update_streaming_restore(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
) -> None:
    """Test that the streaming update entity restores update_percentage, not install_percentage."""

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    entity_id = "update.test_update"
    mock_restore_cache(
        hass,
        (
            State(
                entity_id,
                STATE_ON,
                attributes={
                    "in_progress": True,
                    "update_percentage": 42,
                    "installed_version": "2025.1.1",
                    "latest_version": "2025.2.1",
                },
            ),
        ),
    )

    await setup_platform(hass, [Platform.UPDATE])

    state = hass.states.get(entity_id)
    assert state.attributes["in_progress"] is True
    assert state.attributes["update_percentage"] == 42


async def test_update_streaming_restore_completed_not_in_progress(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
) -> None:
    """Test a stored in-progress flag is dropped when installed == latest.

    Reproduces a stuck "Installing" tile: the completion event never streamed
    because the vehicle went offline mid-install, so the last state kept
    in_progress with no percentage while the versions already matched.
    """

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    entity_id = "update.test_update"
    mock_restore_cache(
        hass,
        (
            State(
                entity_id,
                STATE_ON,
                attributes={
                    "in_progress": True,
                    "update_percentage": None,
                    "installed_version": "2026.26.1",
                    "latest_version": "2026.26.1",
                },
            ),
        ),
    )

    await setup_platform(hass, [Platform.UPDATE])

    state = hass.states.get(entity_id)
    assert state.attributes["in_progress"] is False
    assert state.attributes["update_percentage"] is None


@pytest.mark.parametrize(
    (
        "attributes",
        "extra_data",
        "data",
        "expected_restored",
        "expected_after",
    ),
    [
        pytest.param(
            {
                "in_progress": True,
                "update_percentage": 42,
                "installed_version": "2025.1.1",
                "latest_version": "2025.2.1",
            },
            {
                ATTR_SCHEDULED_AT: None,
                ATTR_DOWNLOAD_PERCENTAGE: 42,
                ATTR_INSTALL_PERCENTAGE: 0,
            },
            {Signal.VERSION: "2025.1.1"},
            (True, 42),
            (True, 42),
            id="download_in_progress",
        ),
        pytest.param(
            {
                "in_progress": False,
                "update_percentage": None,
                "installed_version": "2025.2.1",
                "latest_version": "2025.2.1",
            },
            {
                ATTR_SCHEDULED_AT: None,
                ATTR_DOWNLOAD_PERCENTAGE: 100,
                ATTR_INSTALL_PERCENTAGE: 50,
            },
            {Signal.VERSION: "2025.2.1"},
            (False, None),
            (False, None),
            id="up_to_date_mid_install_leftover",
        ),
        pytest.param(
            {
                "in_progress": True,
                "update_percentage": 50,
                "installed_version": "2025.1.1",
                "latest_version": "2025.2.1",
            },
            {
                ATTR_SCHEDULED_AT: None,
                ATTR_DOWNLOAD_PERCENTAGE: 100,
                ATTR_INSTALL_PERCENTAGE: 50,
            },
            {Signal.VERSION: "2025.2.1"},
            (True, 50),
            (False, None),
            id="install_finished_offline",
        ),
        pytest.param(
            {
                "in_progress": True,
                "update_percentage": 42,
                "installed_version": "2025.1.1",
                "latest_version": "2025.2.1",
            },
            {
                ATTR_SCHEDULED_AT: None,
                ATTR_DOWNLOAD_PERCENTAGE: 42,
                ATTR_INSTALL_PERCENTAGE: 0,
            },
            {Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 100},
            (True, 42),
            (False, None),
            id="download_finished_without_schedule",
        ),
        pytest.param(
            {
                "in_progress": True,
                "update_percentage": 42,
                "installed_version": "2025.1.1",
                "latest_version": "2025.2.1",
            },
            {},
            {Signal.VERSION: "2025.1.1"},
            (True, 42),
            (True, 42),
            id="progress_without_extra_data",
        ),
        pytest.param(
            {
                "in_progress": True,
                "update_percentage": 42,
                "installed_version": "2025.1.1",
                "latest_version": "2025.2.1",
            },
            {
                ATTR_SCHEDULED_AT: None,
                ATTR_DOWNLOAD_PERCENTAGE: None,
                ATTR_INSTALL_PERCENTAGE: None,
            },
            {Signal.VERSION: "2025.1.1"},
            (True, 42),
            (True, 42),
            id="progress_with_unknown_percentages",
        ),
        pytest.param(
            {
                "in_progress": True,
                "update_percentage": 42,
                "installed_version": "2025.1.1",
                "latest_version": "2025.2.1",
            },
            {},
            {Signal.VERSION: "2025.2.1"},
            (True, 42),
            (False, None),
            id="finished_offline_without_extra_data",
        ),
    ],
)
async def test_update_streaming_restore_progress_then_stream_event(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
    attributes: dict[str, bool | int | str | None],
    extra_data: dict[str, int | None],
    data: dict[Signal, str | int],
    expected_restored: tuple[bool, int | None],
    expected_after: tuple[bool, int | None],
) -> None:
    """Test restored percentages drive progress only while an update is outstanding."""

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    entity_id = "update.test_update"
    mock_restore_cache_with_extra_data(
        hass,
        ((State(entity_id, STATE_ON, attributes=attributes), extra_data),),
    )

    await setup_platform(hass, [Platform.UPDATE])

    state = hass.states.get(entity_id)
    assert (
        state.attributes["in_progress"],
        state.attributes["update_percentage"],
    ) == expected_restored

    # A push that leaves a percentage untouched still recomputes progress,
    # so it must use the restored percentages only while they still apply.
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": data,
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert (
        state.attributes["in_progress"],
        state.attributes["update_percentage"],
    ) == expected_after


@pytest.mark.parametrize(
    ("update_percentage", "download_percentage", "data"),
    [
        pytest.param(
            None,
            0,
            {Signal.VERSION: "2025.1.1"},
            id="scheduled_latch",
        ),
        pytest.param(
            42,
            42,
            {Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 100},
            id="download_then_scheduled_latch",
        ),
    ],
)
async def test_update_streaming_restore_current_schedule_expires(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
    freezer: FrozenDateTimeFactory,
    update_percentage: int | None,
    download_percentage: int,
    data: dict[Signal, str | int],
) -> None:
    """Test a restored current schedule re-arms its expiry."""

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    entity_id = "update.test_update"
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State(
                    entity_id,
                    STATE_ON,
                    attributes={
                        "in_progress": True,
                        "update_percentage": update_percentage,
                        "installed_version": "2025.1.1",
                        "latest_version": "2025.2.1",
                    },
                ),
                {
                    ATTR_SCHEDULED_AT: dt_util.utcnow().isoformat(),
                    ATTR_DOWNLOAD_PERCENTAGE: download_percentage,
                    ATTR_INSTALL_PERCENTAGE: 0,
                },
            ),
        ),
    )

    await setup_platform(hass, [Platform.UPDATE])

    # Leaves only the scheduled latch holding in_progress.
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": data,
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.attributes["in_progress"] is True
    assert state.attributes["update_percentage"] is None

    freezer.tick(SCHEDULED_STALE_AFTER + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes["in_progress"] is False
    assert state.attributes["update_percentage"] is None


@pytest.mark.parametrize(
    "extra_data",
    [
        pytest.param(
            {
                ATTR_SCHEDULED_AT: (
                    dt_util.utcnow() - SCHEDULED_STALE_AFTER - timedelta(hours=1)
                ).isoformat(),
                ATTR_DOWNLOAD_PERCENTAGE: 0,
                ATTR_INSTALL_PERCENTAGE: 0,
            },
            id="expired",
        ),
        pytest.param({}, id="never_recorded"),
        pytest.param(
            {ATTR_SCHEDULED_AT: dt_util.utcnow().isoformat()},
            id="incomplete",
        ),
    ],
)
async def test_update_streaming_restore_scheduled_stale(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
    extra_data: dict[str, str | int],
) -> None:
    """Test a latched state without a current schedule restores not in progress."""

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    entity_id = "update.test_update"
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State(
                    entity_id,
                    STATE_ON,
                    attributes={
                        "in_progress": True,
                        "update_percentage": None,
                        "installed_version": "2025.1.1",
                        "latest_version": "2025.2.1",
                    },
                ),
                extra_data,
            ),
        ),
    )

    await setup_platform(hass, [Platform.UPDATE])

    state = hass.states.get(entity_id)
    assert state.attributes["in_progress"] is False
    assert state.attributes["update_percentage"] is None


async def test_update_streaming_extra_data_saved(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the scheduled time and percentages are saved for restore."""

    freezer.move_to("2025-01-01T00:00:00+00:00")
    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    await setup_platform(hass, [Platform.UPDATE])

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 42,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: 0,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: 1735689600,
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()
    await async_mock_restore_state_shutdown_restart(hass)

    stored = next(
        entry
        for entry in hass_storage[RESTORE_STATE_KEY]["data"]
        if entry["state"]["entity_id"] == "update.test_update"
    )
    assert stored["extra_data"] == {
        ATTR_SCHEDULED_AT: "2025-01-01T00:00:00+00:00",
        ATTR_DOWNLOAD_PERCENTAGE: 42,
        ATTR_INSTALL_PERCENTAGE: 0,
    }


async def test_update_streaming_completed_while_scheduled(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
) -> None:
    """Test a scheduled flag does not strand in_progress once installed == latest."""

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    await setup_platform(hass, [Platform.UPDATE])

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: 1735689600,
                Signal.SOFTWARE_UPDATE_VERSION: "2025.2.1",
                Signal.VERSION: "2025.1.1",
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()
    state = hass.states.get("update.test_update")
    assert state.attributes["in_progress"] is True

    # Install finishes while offline: only the new installed version streams,
    # matching latest. The lingering scheduled flag must not keep it in progress.
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: None,
                Signal.VERSION: "2025.2.1",
            },
            "createdAt": "2024-10-04T10:45:18.537Z",
        }
    )
    await hass.async_block_till_done()
    state = hass.states.get("update.test_update")
    assert state.attributes["in_progress"] is False
    assert state.attributes["update_percentage"] is None


@pytest.mark.parametrize(
    ("data", "expected_in_progress", "expected_percentage"),
    [
        pytest.param(
            {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 0,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: None,
            },
            False,
            None,
            id="download_0pct_is_idle",
        ),
        pytest.param(
            {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 1,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: None,
            },
            True,
            1,
            id="download_1pct_is_in_progress",
        ),
        pytest.param(
            {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 100,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: None,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: None,
            },
            False,
            None,
            id="download_100pct_is_complete",
        ),
        pytest.param(
            {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 100,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: 1,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: None,
            },
            False,
            None,
            id="install_1pct_is_not_in_progress",
        ),
        pytest.param(
            {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 100,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: 10,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: None,
            },
            False,
            None,
            id="install_10pct_is_not_in_progress",
        ),
        pytest.param(
            {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 100,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: 11,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: None,
            },
            True,
            11,
            id="install_11pct_is_in_progress",
        ),
        pytest.param(
            {
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE: 100,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE: 100,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME: None,
            },
            False,
            None,
            id="install_100pct_is_complete",
        ),
    ],
)
async def test_update_streaming_progress_thresholds(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
    data: dict[Signal, int | None],
    expected_in_progress: bool,
    expected_percentage: int | None,
) -> None:
    """Test download/install progress threshold edge cases."""

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    await setup_platform(hass, [Platform.UPDATE])

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": data,
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    state = hass.states.get("update.test_update")
    assert state.attributes["in_progress"] is expected_in_progress
    assert state.attributes["update_percentage"] == expected_percentage
