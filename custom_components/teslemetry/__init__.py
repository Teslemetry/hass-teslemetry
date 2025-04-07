"""Teslemetry integration."""

import asyncio
from collections.abc import Callable
from typing import Final

from tesla_fleet_api import Teslemetry
from tesla_fleet_api.const import Scope
from tesla_fleet_api.exceptions import (
    InvalidToken,
    TeslaFleetError,
)
#from tesla_fleet_api.teslemetry import rate_limit
from teslemetry_stream import TeslemetryStream


from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, Platform
from homeassistant.core import HomeAssistant

from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo, async_get as async_get_device_registry
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, LOGGER, MODELS
from .coordinator import (
    TeslemetryEnergySiteInfoCoordinator,
    TeslemetryEnergySiteLiveCoordinator,
    TeslemetryEnergyHistoryCoordinator,
    TeslemetryVehicleDataCoordinator,
)
from .const import TeslemetryState
from .helpers import flatten
from .models import TeslemetryData, TeslemetryEnergyData, TeslemetryVehicleData
from .services import async_register_services

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.COVER,
    Platform.CLIMATE,
    Platform.DEVICE_TRACKER,
    Platform.LOCK,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

type TeslemetryConfigEntry = ConfigEntry[TeslemetryData]

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Telemetry integration."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Teslemetry config."""

    access_token = entry.data[CONF_ACCESS_TOKEN]
    session = async_get_clientsession(hass)

    # Create API connection
    teslemetry = Teslemetry(
        session=session,
        access_token=access_token,
    )
    try:
        calls = await asyncio.gather(
            teslemetry.metadata(),
            teslemetry.products(),
        )
        uid = calls[0]["uid"]
        scopes = calls[0]["scopes"]
        region = calls[0]["region"]
        metadata = calls[0]["vehicles"]
        products = calls[1]["response"]
    except InvalidToken as e:
        raise ConfigEntryAuthFailed from e
    except TeslaFleetError as e:
        raise ConfigEntryNotReady from e
    except TypeError as e:
        LOGGER.error("Invalid response from Teslemetry", e)
        raise ConfigEntryNotReady from e

    if entry.unique_id is None:
        LOGGER.debug("Setting unique_id to %s", uid)
        hass.config_entries.async_update_entry(entry, unique_id=uid)

    device_registry = async_get_device_registry(hass)

    # Create array of classes
    vehicles: list[TeslemetryVehicleData] = []
    energysites: list[TeslemetryEnergyData] = []

    # Create the stream
    stream = TeslemetryStream(
        session, access_token, server="api.teslemetry.com", manual=True
    )


    for product in products:
        if "vin" in product and metadata.get(product["vin"], {}).get("access") and Scope.VEHICLE_DEVICE_DATA in scopes:
            # Remove the protobuff 'cached_data' that we do not use to save memory
            product.pop("cached_data", None)
            vin = product["vin"]
            api = teslemetry.vehicles.create(vin)
            coordinator = TeslemetryVehicleDataCoordinator(hass, api, product)
            firmware = metadata[vin].get("firmware","Unknown")

            device = DeviceInfo(
                identifiers={(DOMAIN, vin)},
                manufacturer="Tesla",
                configuration_url="https://teslemetry.com/console",
                name=product["display_name"],
                model=MODELS.get(vin[3]),
                serial_number=vin,
            )

            device_registry.async_get_or_create(config_entry_id=entry.entry_id, **device)

            remove_listener = stream.async_add_listener(
                create_handle_vehicle_stream(vin, coordinator),
                {"vin": vin},
            )
            stream_vehicle = stream.get_vehicle(vin)

            vehicles.append(
                TeslemetryVehicleData(
                    api=api,
                    config_entry=entry,
                    coordinator=coordinator,
                    stream=stream,
                    stream_vehicle=stream_vehicle,
                    vin=vin,
                    firmware=firmware,
                    device=device,
                    remove_listener=remove_listener
                )
            )
        elif "energy_site_id" in product and Scope.ENERGY_DEVICE_DATA in scopes:
            powerwall = product['components']['battery'] or product['components']['solar']
            wallconnector = "wall_connectors" in product['components']
            if(not powerwall and not wallconnector):
                LOGGER.debug("Skipping Energy Site %s as it has no components", product["energy_site_id"])
                continue

            site_id = product["energy_site_id"]
            api = teslemetry.energySites.create(site_id)

            device = DeviceInfo(
                identifiers={(DOMAIN, str(site_id))},
                manufacturer="Tesla",
                configuration_url="https://teslemetry.com/console",
                name=product.get("site_name", "Energy Site"),
                serial_number=str(site_id),
            )

            device_registry.async_get_or_create(config_entry_id=entry.entry_id, **device)

            energysites.append(
                TeslemetryEnergyData(
                    api=api,
                    live_coordinator=TeslemetryEnergySiteLiveCoordinator(hass, api),
                    info_coordinator=TeslemetryEnergySiteInfoCoordinator(hass, api, product),
                    history_coordinator=TeslemetryEnergyHistoryCoordinator(hass, api) if powerwall else None,
                    id=site_id,
                    device=device,
                )
            )

    # Run all coordinator first refreshes
    await asyncio.gather(
        *(
            async_setup_stream(hass, entry, vehicle)
            for vehicle in vehicles
        ),
        *(
            vehicle.coordinator.async_config_entry_first_refresh()
            for vehicle in vehicles
        ),
        *(
            energysite.live_coordinator.async_config_entry_first_refresh()
            for energysite in energysites
        ),
        *(
            energysite.info_coordinator.async_config_entry_first_refresh()
            for energysite in energysites
        ),
        *(
            energysite.history_coordinator.async_config_entry_first_refresh()
            for energysite in energysites
            if energysite.history_coordinator
        )

    )

    # Enrich devices
    for energysite in energysites:
        models = set()
        for gateway in energysite.info_coordinator.data.get("components_gateways", []):
            if gateway.get("part_name"):
                models.add(gateway["part_name"])
        for battery in energysite.info_coordinator.data.get("components_batteries", []):
            if battery.get("part_name"):
                models.add(battery["part_name"])
        if models:
            energysite.device['model'] = ", ".join(models)

    # Update firwmare
    for vehicle in vehicles:
        vehicle.firmware = vehicle.coordinator.data.get("vehicle_state_car_version", vehicle.firmware).split(" ")[0]

    # Setup Platforms
    entry.runtime_data = TeslemetryData(
        vehicles, energysites, scopes, teslemetry, stream
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_create_background_task(hass, stream.listen(), "Teslemetry Stream")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Teslemetry Config."""
    for vehicle in entry.runtime_data.vehicles:
        vehicle.remove_listener()
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        del entry.runtime_data
    return unload_ok


def create_handle_vehicle_stream(vin: str, coordinator) -> Callable[[dict], None]:
    """Create a handle vehicle stream function."""

    def handle_vehicle_stream(data: dict) -> None:
        """Handle vehicle data from the stream."""
        if "vehicle_data" in data:
            LOGGER.debug("Streaming received new vehicle data from %s", vin)
            coordinator.async_set_updated_data(flatten(data["vehicle_data"]))
        elif "state" in data:
            if coordinator.data["state"] != data["state"]:
                LOGGER.debug("Streaming received new state from %s", vin)
                coordinator.data["state"] = data["state"]
                coordinator.async_set_updated_data(coordinator.data)
        elif "data" in data or "alert" in data or "error" in data:
            if coordinator.data["state"] != TeslemetryState.ONLINE:
                LOGGER.debug("Streaming received telemetry from %s so it must be awake", vin)
                coordinator.data["data"] = TeslemetryState.ONLINE
                coordinator.async_set_updated_data(coordinator.data)

    return handle_vehicle_stream

async def async_setup_stream(hass: HomeAssistant, entry:ConfigEntry, vehicle: TeslemetryVehicleData):
    """Set up the stream for a vehicle."""

    vehicle_stream = vehicle.stream.get_vehicle(vehicle.vin)
    await vehicle_stream.get_config()
    entry.async_create_background_task(hass, vehicle_stream.prefer_typed(True), f"Prefer typed for {vehicle.vin}")
