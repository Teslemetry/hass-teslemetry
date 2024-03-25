"""Teslemetry integration."""

import asyncio
from typing import Final

from tesla_fleet_api import EnergySpecific, Teslemetry, VehicleSpecific
from tesla_fleet_api.const import Scope
from tesla_fleet_api.exceptions import (
    InvalidToken,
    SubscriptionRequired,
    TeslaFleetError,
)
from teslemetry_stream import TeslemetryStream, TeslemetryStreamVehicleNotConfigured


from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, LOGGER, MODELS
from .coordinator import (
    TeslemetryEnergySiteInfoCoordinator,
    TeslemetryEnergySiteLiveCoordinator,
    TeslemetryVehicleDataCoordinator,
)
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
        # scopes = ['openid', 'offline_access', 'user_data', 'vehicle_device_data', 'energy_device_data']
        scopes = (await teslemetry.metadata())["scopes"]
        products = (await teslemetry.products())["response"]
    except InvalidToken:
        LOGGER.error("Access token is invalid, unable to connect to Teslemetry")
        return False
    except SubscriptionRequired:
        LOGGER.error("Subscription required, unable to connect to Telemetry")
        return False
    except TeslaFleetError as e:
        raise ConfigEntryNotReady from e
    except TypeError as e:
        LOGGER.error("Invalid response from Teslemetry", e)
        raise ConfigEntryNotReady from e

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
                session, access_token, vin=vin, parse_timestamp=True
            )
            device = DeviceInfo(
                identifiers={(DOMAIN, vin)},
                manufacturer="Tesla",
                configuration_url="https://teslemetry.com/console",
                name=product["display_name"],
                model=MODELS.get(vin[3]),
                serial_number=vin,
            )

            # Setup Stream
            try:
                async with teslemetry.rate_limit:
                    await stream.get_config()

                    remove_listeners = (
                        stream.async_add_listener(
                            lambda x: hass.bus.fire("teslemetry_alert", x),
                            {"vin": vin, "alerts": None},
                        ),
                        stream.async_add_listener(
                            lambda x: hass.bus.fire("teslemetry_error", x),
                            {"vin": vin, "errors": None},
                        ),
                    )

                    vehicles.append(
                        TeslemetryVehicleData(
                            api=api,
                            coordinator=coordinator,
                            stream=stream,
                            vin=vin,
                            device=device,
                            remove_listeners=remove_listeners,
                        )
                    )
            except TeslemetryStreamVehicleNotConfigured:
                LOGGER.warning(
                    "Vehicle %s is not configured for streaming. Configure at https://teslemetry.com/console/%s",
                    product["display_name"],
                    vin,
                )
            except Exception as e:
                LOGGER.info(
                    "Vehicle %s is unable to use streaming", product["display_name"]
                )
                LOGGER.debug(e)

        elif "energy_site_id" in product and Scope.ENERGY_DEVICE_DATA in scopes:
            site_id = product["energy_site_id"]
            api = EnergySpecific(teslemetry.energy, site_id)
            live_coordinator = TeslemetryEnergySiteLiveCoordinator(hass, api)
            info_coordinator = TeslemetryEnergySiteInfoCoordinator(hass, api, product)
            device = DeviceInfo(
                identifiers={(DOMAIN, str(site_id))},
                manufacturer="Tesla",
                configuration_url="https://teslemetry.com/console",
                name=product.get("site_name", "Energy Site"),
            )

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

    # Setup Platforms
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = TeslemetryData(
        vehicles, energysites, scopes
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Teslemetry Config."""
    for vehicle in hass.data[DOMAIN][entry.entry_id].vehicles:
        for remove_listener in vehicle.remove_listeners:
            remove_listener()
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
