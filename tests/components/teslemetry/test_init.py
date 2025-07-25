"""Test the Teslemetry init."""

from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion
from tesla_fleet_api.exceptions import (
    InvalidToken,
    SubscriptionRequired,
    TeslaFleetError,
)

from homeassistant.components.teslemetry.coordinator import VEHICLE_INTERVAL
from homeassistant.components.teslemetry.models import TeslemetryData
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import setup_platform
from .const import PRODUCTS_MODERN, VEHICLE_DATA_ALT

ERRORS = [
    (InvalidToken, ConfigEntryState.SETUP_ERROR),
    (SubscriptionRequired, ConfigEntryState.SETUP_ERROR),
    (TeslaFleetError, ConfigEntryState.SETUP_RETRY),
]


async def test_load_unload(hass: HomeAssistant) -> None:
    """Test load and unload."""

    entry = await setup_platform(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, TeslemetryData)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not hasattr(entry, "runtime_data")


@pytest.mark.parametrize(("side_effect", "state"), ERRORS)
async def test_init_error(
    hass: HomeAssistant,
    mock_products: AsyncMock,
    side_effect: TeslaFleetError,
    state: ConfigEntryState,
) -> None:
    """Test init with errors."""

    mock_products.side_effect = side_effect
    entry = await setup_platform(hass)
    assert entry.state is state


# Test devices
async def test_devices(
    hass: HomeAssistant, device_registry: dr.DeviceRegistry, snapshot: SnapshotAssertion
) -> None:
    """Test device registry."""
    entry = await setup_platform(hass)
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)

    for device in devices:
        assert device == snapshot(name=f"{device.identifiers}")


@pytest.mark.parametrize(("side_effect", "state"), ERRORS)
async def test_vehicle_refresh_error(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
    side_effect: TeslaFleetError,
    state: ConfigEntryState,
    mock_legacy: AsyncMock,
) -> None:
    """Test coordinator refresh with an error."""
    mock_vehicle_data.side_effect = side_effect
    entry = await setup_platform(hass)
    assert entry.state is state


# Test Energy Live Coordinator
@pytest.mark.parametrize(("side_effect", "state"), ERRORS)
async def test_energy_live_refresh_error(
    hass: HomeAssistant,
    mock_live_status: AsyncMock,
    side_effect: TeslaFleetError,
    state: ConfigEntryState,
) -> None:
    """Test coordinator refresh with an error."""
    mock_live_status.side_effect = side_effect
    entry = await setup_platform(hass)
    assert entry.state is state


# Test Energy Site Coordinator
@pytest.mark.parametrize(("side_effect", "state"), ERRORS)
async def test_energy_site_refresh_error(
    hass: HomeAssistant,
    mock_site_info: AsyncMock,
    side_effect: TeslaFleetError,
    state: ConfigEntryState,
) -> None:
    """Test coordinator refresh with an error."""
    mock_site_info.side_effect = side_effect
    entry = await setup_platform(hass)
    assert entry.state is state


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_vehicle_stream(
    hass: HomeAssistant,
    mock_add_listener: AsyncMock,
    snapshot: SnapshotAssertion,
) -> None:
    """Test vehicle stream events."""

    await setup_platform(hass, [Platform.BINARY_SENSOR])
    mock_add_listener.assert_called()

    state = hass.states.get("binary_sensor.test_status")
    assert state.state == STATE_UNKNOWN

    state = hass.states.get("binary_sensor.test_user_present")
    assert state.state == STATE_UNAVAILABLE

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "vehicle_data": VEHICLE_DATA_ALT["response"],
            "state": "online",
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_status")
    assert state.state == STATE_ON

    state = hass.states.get("binary_sensor.test_user_present")
    assert state.state == STATE_ON

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "state": "offline",
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_status")
    assert state.state == STATE_OFF


async def test_no_live_status(
    hass: HomeAssistant,
    mock_live_status: AsyncMock,
) -> None:
    """Test coordinator refresh with an error."""
    mock_live_status.side_effect = AsyncMock({"response": ""})
    await setup_platform(hass)

    assert hass.states.get("sensor.energy_site_grid_power") is None


async def test_modern_no_poll(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
    mock_products: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that modern vehicles do not poll vehicle_data."""

    mock_products.return_value = PRODUCTS_MODERN
    entry = await setup_platform(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert mock_vehicle_data.called is False
    freezer.tick(VEHICLE_INTERVAL)
    assert mock_vehicle_data.called is False
    freezer.tick(VEHICLE_INTERVAL)
    assert mock_vehicle_data.called is False
