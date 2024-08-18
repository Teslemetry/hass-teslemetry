"""Teslemetry integration."""

import asyncio
from typing import Final

from tesla_fleet_api import EnergySpecific, Teslemetry, VehicleSpecific
from tesla_fleet_api.const import Scope
from tesla_fleet_api.exceptions import (
    InvalidToken,
    SubscriptionRequired,
    TeslaFleetError,
    Forbidden,
)
from tesla_fleet_api.teslemetry import rate_limit
from teslemetry_stream import TeslemetryStream, TeslemetryStreamVehicleNotConfigured


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
    TeslemetryVehicleDataCoordinator,
)
from .helpers import flatten
from .models import TeslemetryData, TeslemetryEnergyData, TeslemetryVehicleData
from .services import async_register_services

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
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
    for product in products:
        if "vin" in product and Scope.VEHICLE_DEVICE_DATA in scopes:
            # Remove the protobuff 'cached_data' that we do not use to save memory
            product.pop("cached_data", None)
            vin = product["vin"]
            api = VehicleSpecific(teslemetry.vehicle, vin)
            coordinator = TeslemetryVehicleDataCoordinator(hass, api, product)
            stream = TeslemetryStream(
                session, access_token, vin=vin, server=f"{region.lower()}.teslemetry.com", parse_timestamp=True
            )

            # Setup AUTO mode
            def _handle_vehicle_data(data: dict) -> None:
                """Handle vehicle data from the stream."""
                coordinator.updated_once = True
                coordinator.async_set_updated_data(flatten(data["vehicle_data"]))

            listener_vehicle_data = stream.async_add_listener(
                    _handle_vehicle_data,
                    {"vin": vin, "vehicle_data": None},
                )

            def _handle_state(data: dict) -> None:
                """Handle state from the stream."""
                coordinator.data["state"] = data["state"]
                coordinator.async_set_updated_data(coordinator.data)

            listener_state = stream.async_add_listener(
                    _handle_state,
                    {"vin": vin, "state": None},
                )

            device = DeviceInfo(
                identifiers={(DOMAIN, vin)},
                manufacturer="Tesla",
                configuration_url="https://teslemetry.com/console",
                name=product["display_name"],
                model=MODELS.get(vin[3]),
                serial_number=vin,
            )

            device_registry.async_get_or_create(config_entry_id=entry.entry_id, **device)

            vehicles.append(
                TeslemetryVehicleData(
                    api=api,
                    coordinator=coordinator,
                    stream=stream,
                    vin=vin,
                    device=device,
                )
            )
        elif "energy_site_id" in product and Scope.ENERGY_DEVICE_DATA in scopes:
            if(not (
                product['components']['battery'] or
                product['components']['solar'] or
                "wall_connectors" in product['components']
            )):
                LOGGER.debug("Skipping Energy Site %s as it has no components", product["energy_site_id"])
                continue

            site_id = product["energy_site_id"]
            api = EnergySpecific(teslemetry.energy, site_id)
            live_coordinator = TeslemetryEnergySiteLiveCoordinator(hass, api)
            info_coordinator = TeslemetryEnergySiteInfoCoordinator(hass, api, product)

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
                    live_coordinator=live_coordinator,
                    info_coordinator=info_coordinator,
                    id=site_id,
                    device=device,
                )
            )

    # Run all coordinator first refreshes
    await asyncio.gather(
        *(async_setup_stream(hass, vehicle) for vehicle in vehicles),
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

    # Setup Platforms
    entry.runtime_data = TeslemetryData(
        vehicles, energysites, scopes, teslemetry
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Teslemetry Config."""
    for vehicle in entry.runtime_data.vehicles:
        for remove_listener in vehicle.remove_listeners:
            remove_listener()
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        del entry.runtime_data
    return unload_ok


async def async_setup_stream(hass: HomeAssistant, vehicle: TeslemetryVehicleData):
    """Setup stream for vehicle."""
    LOGGER.debug("Stream Starting Up")
    try:
        async with rate_limit:
            await vehicle.stream.get_config()

            def handle_alerts(event: dict) -> None:
                """Handle stream alerts."""
                if alerts := event.get("alerts"):
                    for alert in alerts:
                        if alert["startedAt"] <= vehicle.last_alert:
                            break
                        alert["vin"] = vehicle.vin
                        hass.bus.fire("teslemetry_alert", alert)
                    vehicle.last_alert = alerts[0]["startedAt"]

            def handle_errors(event: dict) -> None:
                """Handle stream errors."""
                if errors := event.get("errors"):
                    for error in errors:
                        if error["startedAt"] <= vehicle.last_error:
                            break
                        error["vin"] = vehicle.vin
                        hass.bus.fire("teslemetry_error", error)
                    vehicle.last_error = errors[0]["startedAt"]

            def handle_vehicle_data(data: dict) -> None:
                """Handle vehicle data from the stream."""
                vehicle.coordinator.updated_once = True
                vehicle.coordinator.async_set_updated_data(flatten(data["vehicle_data"]))

            def handle_state(data: dict) -> None:
                """Handle state from the stream."""
                vehicle.coordinator.data["state"] = data["state"]
                vehicle.coordinator.async_set_updated_data(vehicle.coordinator.data)

            vehicle.remove_listeners = (
                vehicle.stream.async_add_listener(
                    handle_alerts,
                    {"vin": vehicle.vin, "alerts": None},
                ),
                vehicle.stream.async_add_listener(
                    handle_errors,
                    {"vin": vehicle.vin, "errors": None},
                ),
                vehicle.stream.async_add_listener(
                    handle_vehicle_data,
                    {"vin": vehicle.vin, "vehicle_data": None},
                ),
                vehicle.stream.async_add_listener(
                    handle_state,
                    {"vin": vehicle.vin, "state": None},
                )
            )

    except TeslemetryStreamVehicleNotConfigured:
        LOGGER.warning(
            "Vehicle %s is not configured for streaming. Configure at https://teslemetry.com/console/%s",
            vehicle.vin,
            vehicle.vin,
        )
    except Exception as e:
        LOGGER.info("Vehicle %s is unable to use streaming", vehicle.vin)
        LOGGER.debug(e)
