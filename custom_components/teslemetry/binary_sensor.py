"""Binary Sensor platform for Teslemetry integration."""

from __future__ import annotations

from itertools import chain
from collections.abc import Callable
from dataclasses import dataclass

from tesla_fleet_api.const import TelemetryField

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import DOMAIN, TeslemetryState, TeslemetryTimestamp
from .entity import (
    TeslemetryVehicleEntity,
    TeslemetryEnergyLiveEntity,
    TeslemetryEnergyInfoEntity,
    TeslemetryVehicleStreamEntity,
)
from .models import TeslemetryVehicleData, TeslemetryEnergyData
from .helpers import auto_type


@dataclass(frozen=True, kw_only=True)
class TeslemetryBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes Teslemetry binary sensor entity."""

    is_on: Callable[[StateType], bool] = lambda x: bool(x)
    timestamp_key: TeslemetryTimestamp | None = None
    streaming_key: TelemetryField | None = None


VEHICLE_DESCRIPTIONS: tuple[TeslemetryBinarySensorEntityDescription, ...] = (
    TeslemetryBinarySensorEntityDescription(
        key="state",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        is_on=lambda x: x == TeslemetryState.ONLINE,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_battery_heater_on",
        streaming_key=TelemetryField.BATTERY_HEATER_ON,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        device_class=BinarySensorDeviceClass.HEAT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_charger_phases",
        streaming_key=TelemetryField.CHARGER_PHASES,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        is_on=lambda x: int(x) > 1,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_preconditioning_enabled",
        streaming_key=TelemetryField.PRECONDITIONING_ENABLED,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="climate_state_is_preconditioning",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_scheduled_charging_pending",
        streaming_key=TelemetryField.SCHEDULED_CHARGING_PENDING,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_trip_charging",
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_conn_charge_cable",
        is_on=lambda x: x != "<invalid>",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="climate_state_cabin_overheat_protection_actively_cooling",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        device_class=BinarySensorDeviceClass.HEAT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_dashcam_state",
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on=lambda x: x == "Recording",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_is_user_present",
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.PRESENCE,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_tpms_soft_warning_fl",
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_tpms_soft_warning_fr",
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_tpms_soft_warning_rl",
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_tpms_soft_warning_rr",
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_fd_window",
        streaming_key=TelemetryField.FD_WINDOW,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_fp_window",
        streaming_key=TelemetryField.FP_WINDOW,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_rd_window",
        streaming_key=TelemetryField.RD_WINDOW,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_rp_window",
        streaming_key=TelemetryField.RP_WINDOW,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_df",
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.DOOR,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_dr",
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.DOOR,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_pf",
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.DOOR,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_pr",
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=BinarySensorDeviceClass.DOOR,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


@dataclass(frozen=True, kw_only=True)
class TeslemetryStreamBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes Teslemetry binary sensor entity."""

    is_on: Callable[[StateType], bool] = lambda x: x.lower() == "true"


VEHICLE_STREAM_DESCRIPTIONS: tuple[
    TeslemetryStreamBinarySensorEntityDescription, ...
] = (
    TeslemetryStreamBinarySensorEntityDescription(
        key=TelemetryField.AUTOMATIC_BLIND_SPOT_CAMERA,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamBinarySensorEntityDescription(
        key=TelemetryField.AUTOMATIC_EMERGENCY_BRAKING_OFF,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamBinarySensorEntityDescription(
        key=TelemetryField.BLIND_SPOT_COLLISION_WARNING_CHIME,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamBinarySensorEntityDescription(
        key=TelemetryField.BMS_FULL_CHARGE_COMPLETE,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamBinarySensorEntityDescription(
        key=TelemetryField.BRAKE_PEDAL,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamBinarySensorEntityDescription(
        key=TelemetryField.CHARGE_ENABLE_REQUEST,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamBinarySensorEntityDescription(
        key=TelemetryField.CHARGE_PORT_COLD_WEATHER_MODE,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamBinarySensorEntityDescription(
        key=TelemetryField.SERVICE_MODE,
        entity_registry_enabled_default=False,
    ),
)

ENERGY_LIVE_DESCRIPTIONS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(key="backup_capable"),
    BinarySensorEntityDescription(key="grid_services_active"),
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
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        chain(
            (  # Vehicles
                TeslemetryVehicleBinarySensorEntity(vehicle, description)
                for vehicle in data.vehicles
                for description in VEHICLE_DESCRIPTIONS
            ),
            (  # Energy Site Live
                TeslemetryEnergyLiveBinarySensorEntity(energysite, description)
                for energysite in data.energysites
                for description in ENERGY_LIVE_DESCRIPTIONS
                if energysite.info_coordinator.data.get("components_battery")
            ),
            (  # Energy Site Info
                TeslemetryEnergyInfoBinarySensorEntity(energysite, description)
                for energysite in data.energysites
                for description in ENERGY_INFO_DESCRIPTIONS
                if energysite.info_coordinator.data.get("components_battery")
            ),
        )
    )


class TeslemetryVehicleBinarySensorEntity(TeslemetryVehicleEntity, BinarySensorEntity):
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
            data, description.key, description.timestamp_key, description.streaming_key
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the binary sensor."""

        if self.coordinator.updated_once:
            if self._value is None:
                self._attr_available = False
                self._attr_is_on = None
            else:
                self._attr_available = True
                self._attr_is_on = self.entity_description.is_on(self._value)
        else:
            self._attr_is_on = None

    def _async_value_from_stream(self, value) -> None:
        """Update the value from the stream."""
        self._attr_available = True
        self._attr_is_on = self.entity_description.is_on(auto_type(value))


class TeslemetryStreamBinarySensorEntity(
    TeslemetryVehicleStreamEntity, BinarySensorEntity
):
    """Base class for Teslemetry vehicle streaming sensors."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        self._attr_native_value = self.entity_description.value_fn(value)


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
