"""Service calls for the Teslemetry integration."""

import logging
import voluptuous as vol
import time
from tesla_fleet_api.exceptions import TeslaFleetError
from voluptuous import All, Range

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_LATITUDE,
    CONF_LONGITUDE
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
from .helpers import wake_up_vehicle, handle_vehicle_command

_LOGGER = logging.getLogger(__name__)
ID = "id"
GPS = "gps"
TYPE = "type"
VALUE = "value"
LOCALE = "locale"
ORDER = "order"
TIMESTAMP = "timestamp"
FIELDS = "fields"
ENABLE = "enable"
TIME = "time"
PIN = "pin"

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
    for vehicle in config.runtime_data.vehicles:
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
            await handle_vehicle_command(
                vehicle.api.navigation_gps_request(
                    lat=call.data[GPS][CONF_LATITUDE],
                    lon=call.data[GPS][CONF_LONGITUDE],
                    order=call.data.get(ORDER),
                )
            )
        except TeslaFleetError as e:
            raise HomeAssistantError from e

    hass.services.async_register(
        DOMAIN,
        "navigation_gps_request",
        navigate_gps_request,
        schema=vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): cv.string,
                vol.Required(GPS): {
                    vol.Required(CONF_LATITUDE): cv.latitude,
                    vol.Required(CONF_LONGITUDE): cv.longitude,
                },
                vol.Optional(ORDER): cv.positive_int,
            }
        ),
    )

    async def navigate_sc_request(call: ServiceCall) -> None:
        """Send supercharger navigation request."""
        device = async_get_device_for_service_call(hass, call)
        config = async_get_config_for_device(hass, device)
        vehicle = async_get_vehicle_for_entry(hass, device, config)

        try:
            await wake_up_vehicle(vehicle)
            await handle_vehicle_command(
                vehicle.api.navigation_sc_request(
                    id=call.data.get(ID),
                    order=call.data.get(ORDER),
                )
            )
        except TeslaFleetError as e:
            raise HomeAssistantError from e

    hass.services.async_register(
        DOMAIN,
        "navigation_sc_request",
        navigate_sc_request,
        schema=vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): cv.string,
                vol.Required(ID): cv.positive_int,
                vol.Optional(ORDER): cv.positive_int,
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
            await handle_vehicle_command(
                vehicle.api.navigation_request(
                    type=call.data.get(TYPE),
                    value=call.data.get(VALUE),
                    locale=call.data.get(LOCALE),
                    timestamp=call.data.get(TIMESTAMP),
                )
            )
        except TeslaFleetError as e:
            raise HomeAssistantError from e

    hass.services.async_register(
        DOMAIN,
        "navigation_request",
        navigate_request,
        schema=vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): cv.string,
                vol.Required(TYPE): cv.string,
                vol.Required(VALUE): cv.string,
                vol.Required(LOCALE): cv.string,
                vol.Optional(TIMESTAMP): cv.positive_int,
            }
        ),
    )

    async def set_scheduled_charging(call: ServiceCall) -> None:
        """Configure fleet telemetry."""
        device = async_get_device_for_service_call(hass, call)
        config = async_get_config_for_device(hass, device)
        vehicle = async_get_vehicle_for_entry(hass, device, config)

        # Convert time to minutes since minute
        if "time" in call.data:
            (hours,minutes,*seconds) = call.data["time"].split(":")
            time = int(hours)*60 + int(minutes)
        elif call.data["enable"]:
            raise ServiceValidationError("Time required to enable scheduled charging")
        else:
            time = None

        try:
            await wake_up_vehicle(vehicle)
            await handle_vehicle_command(vehicle.api.set_scheduled_charging(enable=call.data["enable"], time=time))
        except TeslaFleetError as e:
            raise HomeAssistantError from e

    hass.services.async_register(
        DOMAIN,
        "set_scheduled_charging",
        set_scheduled_charging,
        schema=vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): cv.string,
                vol.Required(ENABLE): bool,
                vol.Optional(TIME): str
            }
        ),
    )

    async def set_scheduled_departure(call: ServiceCall) -> None:
        """Configure fleet telemetry."""
        device = async_get_device_for_service_call(hass, call)
        config = async_get_config_for_device(hass, device)
        vehicle = async_get_vehicle_for_entry(hass, device, config)


        enable = call.data.get("enable",True)

        # Preconditioning
        preconditioning_enabled = call.data.get("preconditioning_enabled",False)
        preconditioning_weekdays_only = call.data.get("preconditioning_weekdays_only", False)
        if "departure_time" in call.data:
            (hours,minutes,*seconds) = call.data["departure_time"].split(":")
            departure_time = int(hours)*60 + int(minutes)
        elif preconditioning_enabled:
            raise ServiceValidationError("Departure time required to enable preconditioning")
        else:
            departure_time = 0

        # Off peak charging
        off_peak_charging_enabled = call.data.get("off_peak_charging_enabled",False)
        off_peak_charging_weekdays_only = call.data.get("off_peak_charging_weekdays_only", False)
        if "end_off_peak_time" in call.data:
            (hours,minutes,*seconds) = call.data["end_off_peak_time"].split(":")
            end_off_peak_time = int(hours)*60 + int(minutes)
        elif off_peak_charging_enabled:
            raise ServiceValidationError("End off peak time required to enable off peak charging")
        else:
            end_off_peak_time = 0

        try:
            await wake_up_vehicle(vehicle)
            await handle_vehicle_command(vehicle.api.set_scheduled_departure(
                enable,
                preconditioning_enabled,
                preconditioning_weekdays_only,
                departure_time,
                off_peak_charging_enabled,
                off_peak_charging_weekdays_only,
                end_off_peak_time
            ))

        except TeslaFleetError as e:
            raise HomeAssistantError from e

    hass.services.async_register(
        DOMAIN,
        "set_scheduled_departure",
        set_scheduled_departure,
        schema=vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): cv.string,
                vol.Optional(ENABLE): bool,
                vol.Optional("preconditioning_enabled"): bool,
                vol.Optional("preconditioning_weekdays_only"): bool,
                vol.Optional("departure_time"): str,
                vol.Optional("off_peak_charging_enabled"): bool,
                vol.Optional("off_peak_charging_weekdays_only"): bool,
                vol.Optional("end_off_peak_time"): str
            }
        ),
    )

    async def stream_fields(call: ServiceCall) -> None:
        """Configure fleet telemetry."""
        device = async_get_device_for_service_call(hass, call)
        config = async_get_config_for_device(hass, device)
        vehicle = async_get_vehicle_for_entry(hass, device, config)

        try:
            resp = await vehicle.stream.replace_fields(fields=call.data[FIELDS])
        except Exception as e:
            raise HomeAssistantError from e
        if "error" in resp:
            raise ServiceValidationError(resp["error"])

    hass.services.async_register(
        DOMAIN,
        "stream_fields",
        stream_fields,
        schema=vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): cv.string,
                vol.Required(FIELDS): dict,
            }
        ),
    )

    async def valet_mode(call: ServiceCall) -> None:
        """Configure fleet telemetry."""
        device = async_get_device_for_service_call(hass, call)
        config = async_get_config_for_device(hass, device)
        vehicle = async_get_vehicle_for_entry(hass, device, config)

        try:
            await wake_up_vehicle(vehicle)
            await handle_vehicle_command(vehicle.api.set_valet_mode(
                call.data.get("enable"),
                call.data.get("pin","")
            ))

        except TeslaFleetError as e:
            raise HomeAssistantError from e

    hass.services.async_register(
        DOMAIN,
        "valet_mode",
        valet_mode,
        schema=vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): cv.string,
                vol.Required(ENABLE): cv.boolean,
                vol.Required(PIN): All(cv.positive_int, Range(min=1000, max=9999)),
            }
        ),
    )

    async def speed_limit(call: ServiceCall) -> None:
        """Configure fleet telemetry."""
        device = async_get_device_for_service_call(hass, call)
        config = async_get_config_for_device(hass, device)
        vehicle = async_get_vehicle_for_entry(hass, device, config)

        try:
            await wake_up_vehicle(vehicle)
            enable = call.data.get("enable")
            if (enable is True):
                await handle_vehicle_command(vehicle.api.speed_limit_activate(
                    call.data.get("pin")
                ))
            elif (enable is False):
                await handle_vehicle_command(vehicle.api.speed_limit_deactivate(
                    call.data.get("pin")
                ))

        except TeslaFleetError as e:
            raise HomeAssistantError from e

    hass.services.async_register(
        DOMAIN,
        "speed_limit",
        speed_limit,
        schema=vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): cv.string,
                vol.Required(ENABLE): cv.boolean,
                vol.Required(PIN): All(cv.positive_int, Range(min=1000, max=9999)),
            }
        ),
    )