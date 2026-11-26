"""Test the Teslemetry Roadster vacuum Labs easter egg."""

from typing import Any
from unittest.mock import patch

import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.labs import async_update_preview_feature
from homeassistant.components.teslemetry.const import (
    DOMAIN,
    LABS_ROADSTER_VACUUM_FEATURE,
)
from homeassistant.components.vacuum import (
    ATTR_FAN_SPEED,
    DOMAIN as VACUUM_DOMAIN,
    SERVICE_CLEAN_SPOT,
    SERVICE_LOCATE,
    SERVICE_PAUSE,
    SERVICE_RETURN_TO_BASE,
    SERVICE_SEND_COMMAND,
    SERVICE_SET_FAN_SPEED,
    SERVICE_START,
    SERVICE_STOP,
    VacuumActivity,
)
from homeassistant.const import ATTR_COMMAND, ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from . import reload_platform, setup_platform

PLATFORMS = [Platform.SENSOR, Platform.VACUUM]
VACUUM_ENTITY_ID = "vacuum.tesla_roadster"
BATTERY_ENTITY_ID = "sensor.tesla_roadster_battery"


async def _async_set_roadster_preview_feature(
    hass: HomeAssistant, enabled: bool
) -> None:
    """Set the Roadster vacuum preview feature without reloading entries."""
    with patch.object(hass.config_entries, "async_schedule_reload"):
        await async_update_preview_feature(
            hass, DOMAIN, LABS_ROADSTER_VACUUM_FEATURE, enabled
        )
        await hass.async_block_till_done()


@pytest.fixture
async def roadster(hass: HomeAssistant) -> None:
    """Set up Teslemetry with the Roadster vacuum preview feature enabled."""
    assert await async_setup_component(hass, "labs", {})
    await _async_set_roadster_preview_feature(hass, True)
    await setup_platform(hass, PLATFORMS)


async def _async_call(
    hass: HomeAssistant, service: str, data: dict[str, Any] | None = None
) -> None:
    """Call a vacuum service on the Roadster."""
    await hass.services.async_call(
        VACUUM_DOMAIN,
        service,
        {ATTR_ENTITY_ID: VACUUM_ENTITY_ID, **(data or {})},
        blocking=True,
    )


def _assert_roadster(
    hass: HomeAssistant, activity: VacuumActivity, battery: int
) -> None:
    """Assert the Roadster activity and battery level."""
    assert (state := hass.states.get(VACUUM_ENTITY_ID))
    assert state.state == activity
    assert (battery_state := hass.states.get(BATTERY_ENTITY_ID))
    assert battery_state.state == str(battery)


async def test_roadster_disabled_by_default(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test nothing is created while the preview feature is off."""
    assert await async_setup_component(hass, "labs", {})
    entry = await setup_platform(hass, PLATFORMS)

    assert not hass.states.async_entity_ids(VACUUM_DOMAIN)
    assert entity_registry.async_get(BATTERY_ENTITY_ID) is None
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, f"{entry.entry_id}_roadster"), entry.entry_id
        )
        is None
    )


@pytest.mark.usefixtures("roadster")
async def test_roadster_entities(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the Roadster vacuum and battery sensor states."""
    assert hass.states.get(VACUUM_ENTITY_ID) == snapshot(name="vacuum")
    assert hass.states.get(BATTERY_ENTITY_ID) == snapshot(name="battery")


@pytest.mark.parametrize(
    ("service", "data", "activity", "battery"),
    [
        pytest.param(SERVICE_START, None, VacuumActivity.CLEANING, 95, id="start"),
        pytest.param(SERVICE_PAUSE, None, VacuumActivity.PAUSED, 100, id="pause"),
        pytest.param(SERVICE_STOP, None, VacuumActivity.IDLE, 100, id="stop"),
        pytest.param(
            SERVICE_CLEAN_SPOT, None, VacuumActivity.CLEANING, 98, id="clean_spot"
        ),
        pytest.param(SERVICE_LOCATE, None, VacuumActivity.DOCKED, 100, id="locate"),
        pytest.param(
            SERVICE_SEND_COMMAND,
            {ATTR_COMMAND: "fly"},
            VacuumActivity.CLEANING,
            90,
            id="fly",
        ),
        pytest.param(
            SERVICE_SEND_COMMAND,
            {ATTR_COMMAND: "hover"},
            VacuumActivity.CLEANING,
            95,
            id="hover",
        ),
        pytest.param(
            SERVICE_SEND_COMMAND,
            {ATTR_COMMAND: "barrel_roll"},
            VacuumActivity.CLEANING,
            85,
            id="barrel_roll",
        ),
        pytest.param(
            SERVICE_SEND_COMMAND,
            {ATTR_COMMAND: "land"},
            VacuumActivity.IDLE,
            100,
            id="land",
        ),
    ],
)
@pytest.mark.usefixtures("roadster")
async def test_roadster_services(
    hass: HomeAssistant,
    service: str,
    data: dict[str, Any] | None,
    activity: VacuumActivity,
    battery: int,
) -> None:
    """Test each Roadster service changes its state optimistically."""
    await _async_call(hass, service, data)

    _assert_roadster(hass, activity, battery)


@pytest.mark.usefixtures("roadster")
async def test_roadster_return_to_base_recharges(hass: HomeAssistant) -> None:
    """Test returning to base docks and fully charges the Roadster."""
    await _async_call(hass, SERVICE_START)
    _assert_roadster(hass, VacuumActivity.CLEANING, 95)

    await _async_call(hass, SERVICE_RETURN_TO_BASE)

    _assert_roadster(hass, VacuumActivity.DOCKED, 100)


@pytest.mark.usefixtures("roadster")
async def test_roadster_set_fan_speed(hass: HomeAssistant) -> None:
    """Test the Roadster can clean upside down."""
    await _async_call(hass, SERVICE_SET_FAN_SPEED, {ATTR_FAN_SPEED: "upside_down"})

    assert (state := hass.states.get(VACUUM_ENTITY_ID))
    assert state.attributes[ATTR_FAN_SPEED] == "upside_down"


@pytest.mark.parametrize(
    ("service", "data", "translation_key"),
    [
        pytest.param(
            SERVICE_SET_FAN_SPEED,
            {ATTR_FAN_SPEED: "warp"},
            "roadster_invalid_fan_speed",
            id="invalid_fan_speed",
        ),
        pytest.param(
            SERVICE_SEND_COMMAND,
            {ATTR_COMMAND: "time_travel"},
            "roadster_unknown_trick",
            id="unknown_trick",
        ),
    ],
)
@pytest.mark.usefixtures("roadster")
async def test_roadster_invalid_input(
    hass: HomeAssistant,
    service: str,
    data: dict[str, Any],
    translation_key: str,
) -> None:
    """Test the Roadster rejects fan speeds and tricks it does not have."""
    with pytest.raises(ServiceValidationError) as exc_info:
        await _async_call(hass, service, data)

    assert exc_info.value.translation_key == translation_key


@pytest.mark.usefixtures("roadster")
async def test_roadster_low_battery(hass: HomeAssistant) -> None:
    """Test a trick the battery cannot afford is refused."""
    for _ in range(6):
        await _async_call(hass, SERVICE_SEND_COMMAND, {ATTR_COMMAND: "barrel_roll"})
    _assert_roadster(hass, VacuumActivity.CLEANING, 10)

    with pytest.raises(ServiceValidationError) as exc_info:
        await _async_call(hass, SERVICE_SEND_COMMAND, {ATTR_COMMAND: "barrel_roll"})

    assert exc_info.value.translation_key == "roadster_low_battery"
    _assert_roadster(hass, VacuumActivity.CLEANING, 10)


async def test_roadster_labs_toggle_triggers_reload(hass: HomeAssistant) -> None:
    """Test toggling the Roadster preview feature schedules an entry reload."""
    assert await async_setup_component(hass, "labs", {})
    entry = await setup_platform(hass, PLATFORMS)

    with patch.object(hass.config_entries, "async_schedule_reload") as mock_reload:
        await async_update_preview_feature(
            hass, DOMAIN, LABS_ROADSTER_VACUUM_FEATURE, True
        )
        await hass.async_block_till_done()

    mock_reload.assert_called_once_with(entry.entry_id)


async def test_roadster_removed_when_disabled(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test turning the preview feature off removes the Roadster and its device."""
    assert await async_setup_component(hass, "labs", {})
    await _async_set_roadster_preview_feature(hass, True)
    entry = await setup_platform(hass, PLATFORMS)
    identifier = (DOMAIN, f"{entry.entry_id}_roadster")

    assert entity_registry.async_get(VACUUM_ENTITY_ID) is not None
    assert (
        device_registry.async_get_device_by_identifier(identifier, entry.entry_id)
        is not None
    )

    await _async_set_roadster_preview_feature(hass, False)
    await reload_platform(hass, entry, PLATFORMS)

    assert entity_registry.async_get(VACUUM_ENTITY_ID) is None
    assert entity_registry.async_get(BATTERY_ENTITY_ID) is None
    assert (
        device_registry.async_get_device_by_identifier(identifier, entry.entry_id)
        is None
    )
