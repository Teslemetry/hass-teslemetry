"""Test the Teslemetry binary sensor platform."""

from unittest.mock import AsyncMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion
from tesla_fleet_api.exceptions import TeslaFleetError
from teslemetry_stream import Signal

from homeassistant.components.teslemetry.const import (
    CONF_SITE_ID,
    SUBENTRY_TYPE_ENERGY_SITE,
)
from homeassistant.components.teslemetry.coordinator import (
    ENERGY_LIVE_INTERVAL,
    VEHICLE_INTERVAL,
)
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_HOST, CONF_PASSWORD, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import assert_entities, assert_entities_alt, mock_config_entry, setup_platform
from .const import VEHICLE_DATA_ALT

from tests.common import MockConfigEntry, async_fire_time_changed


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_binary_sensor(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the binary sensor entities are correct."""

    entry = await setup_platform(hass, [Platform.BINARY_SENSOR])
    assert_entities(hass, entry.entry_id, entity_registry, snapshot)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_binary_sensor_refresh(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_vehicle_data: AsyncMock,
    freezer: FrozenDateTimeFactory,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the binary sensor entities are correct."""

    entry = await setup_platform(hass, [Platform.BINARY_SENSOR])

    # Refresh
    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    freezer.tick(VEHICLE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert_entities_alt(hass, entry.entry_id, entity_registry, snapshot)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_binary_sensors_streaming(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
) -> None:
    """Tests that the binary sensor entities with streaming are correct."""

    freezer.move_to("2024-01-01 00:00:00+00:00")

    entry = await setup_platform(hass, [Platform.BINARY_SENSOR])

    # Stream update
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.FD_WINDOW: "WindowStateOpened",
                Signal.FP_WINDOW: "INVALID_VALUE",
                Signal.RD_WINDOW: "WindowStateClosed",
                Signal.RP_WINDOW: "WindowStatePartiallyOpen",
                Signal.DOOR_STATE: {
                    "DoorState": {
                        "DriverFront": True,
                        "DriverRear": False,
                        "PassengerFront": False,
                        "PassengerRear": False,
                        "TrunkFront": False,
                        "TrunkRear": False,
                    }
                },
                Signal.DRIVER_SEAT_BELT: None,
                Signal.REAR_DEFROST_ENABLED: True,
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    # Reload the entry
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    # Assert the entities restored their values with concrete assertions
    assert hass.states.get("binary_sensor.test_front_driver_window").state == "on"
    assert hass.states.get("binary_sensor.test_front_passenger_window").state == "off"
    assert hass.states.get("binary_sensor.test_rear_driver_window").state == "off"
    assert hass.states.get("binary_sensor.test_rear_passenger_window").state == "on"
    assert hass.states.get("binary_sensor.test_front_driver_door").state == "off"
    assert hass.states.get("binary_sensor.test_front_passenger_door").state == "off"
    assert hass.states.get("binary_sensor.test_driver_seat_belt").state == "off"
    assert hass.states.get("binary_sensor.test_rear_defroster").state == "on"


async def test_binary_sensors_connectivity(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
) -> None:
    """Tests that the binary sensor entities with streaming are correct."""

    freezer.move_to("2024-01-01 00:00:00+00:00")

    await setup_platform(hass, [Platform.BINARY_SENSOR])

    # Stream update
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "status": "CONNECTED",
            "networkInterface": "cellular",
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "status": "DISCONNECTED",
            "networkInterface": "wifi",
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    # Assert the entities have correct state with concrete assertions
    assert hass.states.get("binary_sensor.test_cellular").state == "on"
    assert hass.states.get("binary_sensor.test_wi_fi").state == "off"


SITE_ID = 123456
HOST = "192.168.91.1"
PASSWORD = "abcde"

# aiopowerwall's PowerwallClient parses the PEM at construction, so a paired
# site needs a real (if undersized, for speed) RSA key rather than fake bytes.
_TEST_RSA_KEY_PEM = rsa.generate_private_key(
    public_exponent=65537, key_size=1024
).private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
)

# Local gateway live_status: grid_status differs from the cloud fixture
# ("Active") so a reroute is observable, and the cloud-only booleans come back
# None as the local adapter actually returns them.
LOCAL_LIVE_STATUS = {
    "response": {
        "solar_power": 2000,
        "energy_left": 20000,
        "total_pack_energy": 40000,
        "percentage_charged": 80.0,
        "backup_capable": None,
        "battery_power": 3000,
        "load_power": 4000,
        "grid_status": "Inactive",
        "grid_services_active": None,
        "grid_power": 1000,
        "grid_services_power": None,
        "generator_power": 500,
        "island_status": "off_grid",
        "storm_mode_active": None,
        "timestamp": None,
        "wall_connectors": None,
    }
}


def _paired_entry() -> MockConfigEntry:
    """Return a config entry whose energy site is paired for local control."""
    entry = mock_config_entry()
    return MockConfigEntry(
        domain=entry.domain,
        version=entry.version,
        minor_version=entry.minor_version,
        unique_id=entry.unique_id,
        data=dict(entry.data),
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
                unique_id=str(SITE_ID),
                title="Energy Site",
                data={
                    CONF_SITE_ID: SITE_ID,
                    CONF_HOST: HOST,
                    CONF_PASSWORD: PASSWORD,
                },
            )
        ],
    )


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_paired_site_grid_status_reads_local(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_live_status: AsyncMock,
) -> None:
    """A paired site reroutes only grid status to the local gateway.

    grid status follows the local snapshot while the other live binary sensors
    (backup capable, grid services active, storm watch active) stay on cloud.
    """
    entry = _paired_entry()
    entry.add_to_hass(hass)

    local_live = AsyncMock(return_value=LOCAL_LIVE_STATUS)
    with (
        patch(
            "homeassistant.components.teslemetry._async_get_rsa_key_pem",
            return_value=_TEST_RSA_KEY_PEM,
        ),
        patch(
            "aiopowerwall.energysite.PowerwallEnergySite.live_status",
            new=local_live,
        ),
        patch(
            "homeassistant.components.teslemetry.PLATFORMS",
            [Platform.BINARY_SENSOR],
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        freezer.tick(ENERGY_LIVE_INTERVAL)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        # Cloud grid_status is "Active" (on); the local snapshot is "Inactive".
        assert hass.states.get("binary_sensor.energy_site_grid_status").state == "off"
        # Cloud-only live binary sensors keep their cloud values.
        assert hass.states.get("binary_sensor.energy_site_backup_capable").state == "on"
        assert (
            hass.states.get("binary_sensor.energy_site_grid_services_active").state
            == "off"
        )

        # A cloud outage leaves the rerouted grid status available while the
        # cloud-only binary sensors go unavailable with the cloud coordinator.
        # The cloud coordinator is stream-driven, so fail its retained REST
        # recovery refresh; the local coordinator keeps polling the LAN gateway.
        mock_live_status.side_effect = TeslaFleetError
        cloud_coordinator = entry.runtime_data.energysites[0].live_coordinator
        assert cloud_coordinator is not None
        await cloud_coordinator.async_refresh()
        freezer.tick(ENERGY_LIVE_INTERVAL)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.energy_site_grid_status").state == "off"
    assert (
        hass.states.get("binary_sensor.energy_site_backup_capable").state
        == STATE_UNAVAILABLE
    )
