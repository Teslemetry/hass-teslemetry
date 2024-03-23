import logging
import voluptuous as vol
from tesla_fleet_api.exceptions import TeslaFleetError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DEVICE_ID,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
)


from .const import DOMAIN
from .models import TeslemetryVehicleData
from .helpers import wake_up_vehicle

_LOGGER = logging.getLogger(__name__)
LATITUDE = "latitude"
LONGITUDE = "longitude"
ORDER = "order"
ORDER_DEFAULT = 1


def async_get_device_for_service_call(
    hass: HomeAssistant, call: ServiceCall
) -> dr.DeviceEntry:
    """Get the device entry related to a service call."""
    device_id = call.data[CONF_DEVICE_ID]
    device_registry = dr.async_get(hass)
    if (device_entry := device_registry.async_get(device_id)) is None:
        raise ServiceValidationError(f"Invalid device ID: {device_id}")
    return device_entry


def async_get_config_for_device(
    hass: HomeAssistant, device_entry: dr.DeviceEntry
) -> ConfigEntry:
    """Get the config entry related to a device entry."""
    for entry_id in device_entry.config_entries:
        if (entry := hass.config_entries.async_get_entry(entry_id)) is None:
            continue
        if entry.domain == DOMAIN:
            return entry
    raise ServiceValidationError(f"No config entry for device ID: {device_entry.id}")


def async_get_vehicle_for_entry(
    hass: HomeAssistant, device: dr.DeviceEntry, config: ConfigEntry
) -> TeslemetryVehicleData:
    """Get the vehicle data for a config entry."""
    assert device.serial_number is not None
    for vehicle in hass.data[DOMAIN][config.entry_id].vehicles:
        if vehicle.vin == device.serial_number:
            return vehicle
    raise ServiceValidationError(f"No vehicle data for device ID: {device.id}")


def async_register_services(hass: HomeAssistant) -> bool:
    """Set up the Tessie integration."""

    _LOGGER.info("Registering services")

    async def navigate_gps_request(call: ServiceCall) -> None:
        """Send lat,lon,order with a vehicle."""
        device = async_get_device_for_service_call(hass, call)
        config = async_get_config_for_device(hass, device)
        vehicle = async_get_vehicle_for_entry(hass, device, config)

        try:
            await wake_up_vehicle(vehicle)
            resp = await vehicle.api.navigation_gps_request(
                lat=call.data.get(LATITUDE),
                lon=call.data.get(LONGITUDE),
                order=call.data.get(ORDER, ORDER_DEFAULT),
            )
            print(resp)
        except TeslaFleetError as e:
            raise HomeAssistantError from e

    hass.services.async_register(
        DOMAIN,
        "navigation_gps_request",
        navigate_gps_request,
        schema=vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): cv.string,
                vol.Required(LATITUDE): cv.string,
                vol.Required(LONGITUDE): cv.string,
                vol.Optional(ORDER, default=ORDER_DEFAULT): cv.positive_int,
            }
        ),
    )

    async def navigate_request(call: ServiceCall) -> None:
        """Send lat,lon,order with a vehicle."""
        device = async_get_device_for_service_call(hass, call)
        config = async_get_config_for_device(hass, device)
        vehicle = async_get_vehicle_for_entry(hass, device, config)

        try:
            await wake_up_vehicle(vehicle)
            resp = await vehicle.api.navigation_request(
                lat=call.data.get(LATITUDE),
                lon=call.data.get(LONGITUDE),
                order=call.data.get(ORDER, ORDER_DEFAULT),
            )
            print(resp)
        except TeslaFleetError as e:
            raise HomeAssistantError from e

    hass.services.async_register(
        DOMAIN,
        "navigation_request",
        navigate_request,
        schema=vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): cv.string,
                vol.Required(LATITUDE): cv.string,
                vol.Required(LONGITUDE): cv.string,
                vol.Optional(ORDER, default=ORDER_DEFAULT): cv.positive_int,
            }
        ),
    )

    async def test(call: ServiceCall) -> None:
        """Send lat,lon,order with a vehicle."""
        device = async_get_device_for_service_call(hass, call)
        config = async_get_config_for_device(hass, device)
        vehicle = async_get_vehicle_for_entry(hass, device, config)

        try:
            await wake_up_vehicle(vehicle)
            resp = await vehicle.api.flash_lights()
            print(resp)
        except TeslaFleetError as e:
            raise HomeAssistantError from e

    hass.services.async_register(
        DOMAIN,
        "test",
        test,
        schema=vol.Schema({vol.Required(CONF_DEVICE_ID): cv.string}),
    )
