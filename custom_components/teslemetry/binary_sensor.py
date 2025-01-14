"""Binary Sensor platform for Teslemetry integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from teslemetry_stream import Signal, TeslemetryStreamVehicle

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.helpers.typing import StateType
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import TeslemetryState
from .entity import (
    TeslemetryVehicleEntity,
    TeslemetryEnergyLiveEntity,
    TeslemetryEnergyInfoEntity,
    TeslemetryVehicleStreamEntity,
)
from .models import TeslemetryVehicleData, TeslemetryEnergyData

@dataclass(frozen=True, kw_only=True)
class TeslemetryBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes Teslemetry binary sensor entity."""

    polling_value_fn: Callable[[StateType], bool] = lambda x: bool(x)
    polling: bool = False
    streaming_key: Signal | None = None
    streaming_listener: Callable[[TeslemetryStreamVehicle], Callable] | None = None
    streaming_firmware: str = "2024.26"
    streaming_value_fn: Callable[[StateType], bool] = bool


VEHICLE_DESCRIPTIONS: tuple[TeslemetryBinarySensorEntityDescription, ...] = (
    TeslemetryBinarySensorEntityDescription(
        key="state",
        polling=True,
        polling_value_fn=lambda x: x == TeslemetryState.ONLINE,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_battery_heater_on",
        polling=True,
        streaming_key=Signal.BATTERY_HEATER_ON,
        streaming_listener=lambda s: s.listen_BatteryHeaterOn,
        device_class=BinarySensorDeviceClass.HEAT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_charger_phases",
        polling=True,
        streaming_key=Signal.CHARGER_PHASES,
        streaming_listener=lambda s: s.listen_ChargerPhases,
        polling_value_fn=lambda x: int(x) > 1,
        streaming_value_fn=lambda x: x > 1,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_preconditioning_enabled",
        polling=True,
        streaming_key=Signal.PRECONDITIONING_ENABLED,
        streaming_listener=lambda s: s.listen_PreconditioningEnabled,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="climate_state_is_preconditioning",
        polling=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_scheduled_charging_pending",
        polling=True,
        streaming_key=Signal.SCHEDULED_CHARGING_PENDING,
        streaming_listener=lambda s: s.listen_ScheduledChargingPending,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_trip_charging",
        polling=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_conn_charge_cable",
        polling=True,
        polling_value_fn=lambda x: x != "<invalid>",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="climate_state_cabin_overheat_protection_actively_cooling",
        polling=True,
        device_class=BinarySensorDeviceClass.HEAT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_dashcam_state",
        polling=True,
        device_class=BinarySensorDeviceClass.RUNNING,
        polling_value_fn=lambda x: x == "Recording",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_is_user_present",
        polling=True,
        device_class=BinarySensorDeviceClass.PRESENCE,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_tpms_soft_warning_fl",
        polling=True,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_tpms_soft_warning_fr",
        polling=True,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_tpms_soft_warning_rl",
        polling=True,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_tpms_soft_warning_rr",
        polling=True,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_fd_window",
        polling=True,
        streaming_key=Signal.FD_WINDOW,
        streaming_listener=lambda s: s.listen_FrontDriverWindow,
        streaming_value_fn = lambda x: x != "Closed",
        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_fp_window",
        polling=True,
        streaming_key=Signal.FP_WINDOW,
        streaming_listener=lambda s: s.listen_FrontPassengerWindow,
        streaming_value_fn = lambda x: x != "Closed",
        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_rd_window",
        polling=True,
        streaming_key=Signal.RD_WINDOW,
        streaming_listener=lambda s: s.listen_RearDriverWindow,
        streaming_value_fn = lambda x: x != "Closed",
        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_rp_window",
        polling=True,
        streaming_key=Signal.RP_WINDOW,
        streaming_listener=lambda s: s.listen_RearPassengerWindow,
        streaming_value_fn = lambda x: x != "Closed",
        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_df",
        polling=True,
        device_class=BinarySensorDeviceClass.DOOR,
        streaming_key=Signal.DOOR_STATE,
        streaming_listener=lambda s: s.listen_FrontDriverDoor,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_dr",
        polling=True,
        device_class=BinarySensorDeviceClass.DOOR,
        streaming_key=Signal.DOOR_STATE,
        streaming_listener=lambda s: s.listen_RearDriverDoor,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_pf",
        polling=True,
        device_class=BinarySensorDeviceClass.DOOR,
        streaming_key=Signal.DOOR_STATE,
        streaming_listener=lambda s: s.listen_FrontPassengerDoor,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_pr",
        polling=True,
        device_class=BinarySensorDeviceClass.DOOR,
        streaming_key=Signal.DOOR_STATE,
        streaming_listener=lambda s: s.listen_RearPassengerDoor,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="automatic_blind_spot_camera",
        streaming_key=Signal.AUTOMATIC_BLIND_SPOT_CAMERA,
        streaming_listener=lambda s: s.listen_AutomaticBlindSpotCamera,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="automatic_emergency_braking_off",
        streaming_key=Signal.AUTOMATIC_EMERGENCY_BRAKING_OFF,
        streaming_listener=lambda s: s.listen_AutomaticEmergencyBrakingOff,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="blind_spot_collision_warning_chime",
        streaming_key=Signal.BLIND_SPOT_COLLISION_WARNING_CHIME,
        streaming_listener=lambda s: s.listen_BlindSpotCollisionWarningChime,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="bms_full_charge_complete",
        streaming_key=Signal.BMS_FULL_CHARGE_COMPLETE,
        streaming_listener=lambda s: s.listen_BmsFullchargecomplete,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="brake_pedal",
        streaming_key=Signal.BRAKE_PEDAL,
        streaming_listener=lambda s: s.listen_BrakePedal,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_port_cold_weather_mode",
        streaming_key=Signal.CHARGE_PORT_COLD_WEATHER_MODE,
        streaming_listener=lambda s: s.listen_ChargePortColdWeatherMode,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="service_mode",
        streaming_key=Signal.SERVICE_MODE,
        streaming_listener=lambda s: s.listen_ServiceMode,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="pin_to_drive_enabled",
        streaming_key=Signal.PIN_TO_DRIVE_ENABLED,
        streaming_listener=lambda s: s.listen_PinToDriveEnabled,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="drive_rail",
        streaming_key=Signal.DRIVE_RAIL,
        streaming_listener=lambda s: s.listen_DriveRail,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="driver_seat_belt",
        streaming_key=Signal.DRIVER_SEAT_BELT,
        streaming_listener=lambda s: s.listen_DriverSeatBelt,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="driver_seat_occupied",
        streaming_key=Signal.DRIVER_SEAT_OCCUPIED,
        streaming_listener=lambda s: s.listen_DriverSeatOccupied,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="passenger_seat_belt",
        streaming_key=Signal.PASSENGER_SEAT_BELT,
        streaming_listener=lambda s: s.listen_PassengerSeatBelt,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="fast_charger_present",
        streaming_key=Signal.FAST_CHARGER_PRESENT,
        streaming_listener=lambda s: s.listen_FastChargerPresent,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="gps_state",
        streaming_key=Signal.GPS_STATE,
        streaming_listener=lambda s: s.listen_GpsState,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="guest_mode_enabled",
        streaming_key=Signal.GUEST_MODE_ENABLED,
        streaming_listener=lambda s: s.listen_GuestModeEnabled,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: x is True or x == "true",
    ),
    TeslemetryBinarySensorEntityDescription(
        key="dc_dc_enable",
        streaming_key=Signal.DC_DC_ENABLE,
        streaming_listener=lambda s: s.listen_DCDCEnable,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="emergency_lane_departure_avoidance",
        streaming_key=Signal.EMERGENCY_LANE_DEPARTURE_AVOIDANCE,
        streaming_listener=lambda s: s.listen_EmergencyLaneDepartureAvoidance,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="supercharger_session_trip_planner",
        streaming_key=Signal.SUPERCHARGER_SESSION_TRIP_PLANNER,
        streaming_listener=lambda s: s.listen_SuperchargerSessionTripPlanner,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="wiper_heat_enabled",
        streaming_key=Signal.WIPER_HEAT_ENABLED,
        streaming_listener=lambda s: s.listen_WiperHeatEnabled,
        streaming_firmware = "2024.44.25",
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="rear_display_hvac_enabled",
        streaming_key=Signal.REAR_DISPLAY_HVAC_ENABLED,
        streaming_listener=lambda s: s.listen_RearDisplayHvacEnabled,
        streaming_firmware = "2024.44.25",
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="offroad_lightbar_present",
        streaming_key=Signal.OFFROAD_LIGHTBAR_PRESENT,
        streaming_listener=lambda s: s.listen_OffroadLightbarPresent,
        streaming_firmware = "2024.44.25",
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="homelink_nearby",
        streaming_key=Signal.HOMELINK_NEARBY,
        streaming_listener=lambda s: s.listen_HomelinkNearby,
        streaming_firmware = "2024.44.25",
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="europe_vehicle",
        streaming_key=Signal.EUROPE_VEHICLE,
        streaming_listener=lambda s: s.listen_EuropeVehicle,
        streaming_firmware = "2024.44.25",
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="right_hand_drive",
        streaming_key=Signal.RIGHT_HAND_DRIVE,
        streaming_listener=lambda s: s.listen_RightHandDrive,
        streaming_firmware = "2024.44.25",
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="located_at_home",
        streaming_key=Signal.LOCATED_AT_HOME,
        streaming_listener=lambda s: s.listen_LocatedAtHome,
        streaming_firmware = "2024.44.32",
    ),
    TeslemetryBinarySensorEntityDescription(
        key="located_at_work",
        streaming_key=Signal.LOCATED_AT_WORK,
        streaming_listener=lambda s: s.listen_LocatedAtWork,
        streaming_firmware = "2024.44.32",
    ),
    TeslemetryBinarySensorEntityDescription(
        key="located_at_favorite",
        streaming_key=Signal.LOCATED_AT_FAVORITE,
        streaming_listener=lambda s: s.listen_LocatedAtFavorite,
        streaming_firmware = "2024.44.32",
        entity_registry_enabled_default=False,
    ),
)

ENERGY_LIVE_DESCRIPTIONS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(key="backup_capable"),
    BinarySensorEntityDescription(key="grid_services_active"),
    BinarySensorEntityDescription(key="storm_mode_active"),
)


ENERGY_INFO_DESCRIPTIONS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key="components_grid_services_enabled",
    ),
)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry binary sensor platform from a config entry."""

    entities = []
    for vehicle in entry.runtime_data.vehicles:
        for description in VEHICLE_DESCRIPTIONS:
            if not vehicle.api.pre2021 and description.streaming_key and vehicle.firmware >= description.streaming_firmware:
                entities.append(TeslemetryVehicleStreamingBinarySensorEntity(vehicle, description))
            elif description.polling:
                entities.append(TeslemetryVehiclePollingBinarySensorEntity(vehicle, description))

    entities.extend(
        TeslemetryEnergyLiveBinarySensorEntity(energysite, description)
        for energysite in entry.runtime_data.energysites
        for description in ENERGY_LIVE_DESCRIPTIONS
        if description.key in energysite.live_coordinator.data
    )
    entities.extend(
        TeslemetryEnergyInfoBinarySensorEntity(energysite, description)
        for energysite in entry.runtime_data.energysites
        for description in ENERGY_INFO_DESCRIPTIONS
        if description.key in energysite.info_coordinator.data
    )

    async_add_entities(entities)


class TeslemetryVehiclePollingBinarySensorEntity(TeslemetryVehicleEntity, BinarySensorEntity):
    """Base class for Teslemetry vehicle binary sensors."""

    entity_description: TeslemetryBinarySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetryBinarySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(
            data, description.key
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the binary sensor."""

        self._attr_available = self._value is not None
        if self._attr_available:
            self._attr_is_on = self.entity_description.polling_value_fn(self._value)


class TeslemetryVehicleStreamingBinarySensorEntity(
    TeslemetryVehicleStreamEntity, BinarySensorEntity, RestoreEntity
):
    """Base class for Teslemetry vehicle streaming sensors."""

    entity_description: TeslemetryBinarySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetryBinarySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description

        super().__init__(data, description.key)

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        assert self.entity_description.streaming_listener
        self.async_on_remove(self.entity_description.streaming_listener(self.stream)(self._async_value_from_stream))

        assert self.entity_description.streaming_key
        self.vehicle.config_entry.async_create_background_task(
            self.hass,
            self.stream.add_field(self.entity_description.streaming_key),
            f"Adding field {self.entity_description.streaming_key.value} to {self.vehicle.vin}"
        )

        if (state := await self.async_get_last_state()) is not None:
            self._attr_is_on = state.state == STATE_ON

    def _async_value_from_stream(self, value: StateType) -> None:
        """Update the value of the entity."""
        self._attr_avaliable = value is not None
        if self._attr_avaliable:
            self._attr_is_on = self.entity_description.streaming_value_fn(value)

    def create_callback(self, value_fn: Callable = lambda x: x) -> Callable:
        """Create a callback for the entity."""
        def callback(value):
            self._attr_avaliable = value is not None
            if self._attr_avaliable:
                self._attr_is_on = value_fn(value)
        return callback

class TeslemetryEnergyLiveBinarySensorEntity(
    TeslemetryEnergyLiveEntity, BinarySensorEntity
):
    """Base class for Teslemetry energy live binary sensors."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the binary sensor."""
        self._attr_is_on = self._value


class TeslemetryEnergyInfoBinarySensorEntity(
    TeslemetryEnergyInfoEntity, BinarySensorEntity
):
    """Base class for Teslemetry energy info binary sensors."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the binary sensor."""
        self._attr_is_on = self._value
