"""Sensor platform for Teslemetry integration."""
from __future__ import annotations

from tesla_fleet_api.const import TelemetryField

from itertools import chain
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.util.variance import ignore_variance
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .const import DOMAIN, TeslemetryTimestamp
from .entity import (
    TeslemetryEnergyLiveEntity,
    TeslemetryVehicleEntity,
    TeslemetryWallConnectorEntity,
    TeslemetryEnergyInfoEntity,
)
from .models import TeslemetryEnergyData, TeslemetryVehicleData

ChargeStates = {
    "Starting": "starting",
    "Charging": "charging",
    "Stopped": "stopped",
    "Complete": "complete",
    "Disconnected": "disconnected",
    "NoPower": "no_power",
}

ShiftStates = {"P": "p", "D": "d", "R": "r", "N": "n"}


@dataclass(frozen=True, kw_only=True)
class TeslemetrySensorEntityDescription(SensorEntityDescription):
    """Describes Teslemetry Sensor entity."""

    value_fn: Callable[[StateType], StateType | datetime] = lambda x: x
    streaming_key: TelemetryField | None = None
    timestamp_key: TeslemetryTimestamp | None = None


VEHICLE_DESCRIPTIONS: tuple[TeslemetrySensorEntityDescription, ...] = (
    TeslemetrySensorEntityDescription(
        key="charge_state_charging_state",
        streaming_key=TelemetryField.CHARGE_STATE,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        options=list(ChargeStates.values()),
        device_class=SensorDeviceClass.ENUM,
        value_fn=lambda value: ChargeStates.get(cast(str, value)),
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_battery_level",
        streaming_key=TelemetryField.BATTERY_LEVEL,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_usable_battery_level",
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charge_energy_added",
        streaming_key=TelemetryField.AC_CHARGING_ENERGY_IN,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=1,
        value_fn=ignore_variance(lambda x: x, 0.5),
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_power",
        streaming_key=TelemetryField.AC_CHARGING_POWER,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_voltage",
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_actual_current",
        stream_key=TelemetryField.CHARGE_AMPS,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charge_rate",
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.MILES_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_conn_charge_cable",
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_fast_charger_type",
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_battery_range",
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_est_battery_range",
        streaming_key=TelemetryField.EST_BATTERY_RANGE,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_ideal_battery_range",
        streaming_key=TelemetryField.IDEAL_BATTERY_RANGE,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_speed",
        streaming_key=TelemetryField.VEHICLE_SPEED,
        timestamp_key=TeslemetryTimestamp.DRIVE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.MILES_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        value_fn=lambda value: value or 0,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_power",
        timestamp_key=TeslemetryTimestamp.DRIVE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda value: value or 0,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_shift_state",
        streaming_key=TelemetryField.GEAR,
        timestamp_key=TeslemetryTimestamp.DRIVE_STATE,
        options=list(ShiftStates.values()),
        device_class=SensorDeviceClass.ENUM,
        value_fn=lambda x: ShiftStates.get(x, "p"),
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_odometer",
        streaming_key=TelemetryField.ODOMETER,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_fl",
        streaming_key=TelemetryField.TPMS_PRESSURE_FL,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        # suggested_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_fr",
        streaming_key=TelemetryField.TPMS_PRESSURE_FR,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        # suggested_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_rl",
        streaming_key=TelemetryField.TPMS_PRESSURE_RL,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        # suggested_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_rr",
        streaming_key=TelemetryField.TPMS_PRESSURE_RR,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        # suggested_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_inside_temp",
        streaming_key=TelemetryField.INSIDE_TEMP,
        timestamp_key="climate_state_timestamp",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_outside_temp",
        streaming_key=TelemetryField.OUTSIDE_TEMP,
        timestamp_key="climate_state_timestamp",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_driver_temp_setting",
        timestamp_key="climate_state_timestamp",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_passenger_temp_setting",
        timestamp_key="climate_state_timestamp",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_traffic_minutes_delay",
        timestamp_key=TeslemetryTimestamp.DRIVE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_energy_at_arrival",
        timestamp_key=TeslemetryTimestamp.DRIVE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_miles_to_arrival",
        streaming_key=TelemetryField.MILES_TO_ARRIVAL,
        timestamp_key=TeslemetryTimestamp.DRIVE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
    ),
)


@dataclass(frozen=True, kw_only=True)
class TeslemetryTimeEntityDescription(SensorEntityDescription):
    """Describes Teslemetry Sensor entity."""

    variance: int = 60


VEHICLE_TIME_DESCRIPTIONS: tuple[TeslemetryTimeEntityDescription, ...] = (
    TeslemetryTimeEntityDescription(
        key="charge_state_minutes_to_full_charge",
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryTimeEntityDescription(
        key="drive_state_active_route_minutes_to_arrival",
        streaming_key=TelemetryField.MINUTES_TO_ARRIVAL,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
)

ENERGY_LIVE_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="solar_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    SensorEntityDescription(
        key="energy_left",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="total_pack_energy",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="percentage_charged",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="battery_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    SensorEntityDescription(
        key="load_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    SensorEntityDescription(
        key="grid_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    SensorEntityDescription(
        key="grid_services_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    SensorEntityDescription(
        key="generator_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    SensorEntityDescription(key="island_status", device_class=SensorDeviceClass.ENUM),
)

WALL_CONNECTOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="wall_connector_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.ENUM,
    ),
    SensorEntityDescription(
        key="wall_connector_fault_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.ENUM,
    ),
    SensorEntityDescription(
        key="wall_connector_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    SensorEntityDescription(
        key="vin",
    ),
)

ENERGY_INFO_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="vpp_backup_reserve_percent",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
    ),
    SensorEntityDescription(key="version"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry sensor platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        chain(
            (  # Add vehicles
                TeslemetryVehicleSensorEntity(vehicle, description)
                for vehicle in data.vehicles
                for description in VEHICLE_DESCRIPTIONS
            ),
            (  # Add vehicles time sensors
                TeslemetryVehicleTimeSensorEntity(vehicle, description)
                for vehicle in data.vehicles
                for description in VEHICLE_TIME_DESCRIPTIONS
            ),
            (  # Add energy site live
                TeslemetryEnergyLiveSensorEntity(energysite, description)
                for energysite in data.energysites
                for description in ENERGY_LIVE_DESCRIPTIONS
                if description.key in energysite.live_coordinator.data
            ),
            (  # Add wall connectors
                TeslemetryWallConnectorSensorEntity(energysite, din, description)
                for energysite in data.energysites
                for din in energysite.live_coordinator.data.get("wall_connectors", {})
                for description in WALL_CONNECTOR_DESCRIPTIONS
            ),
            (  # Add energy site info
                TeslemetryEnergyInfoSensorEntity(energysite, description)
                for energysite in data.energysites
                for description in ENERGY_INFO_DESCRIPTIONS
                if description.key in energysite.info_coordinator.data
            ),
        )
    )


class TeslemetryVehicleSensorEntity(TeslemetryVehicleEntity, SensorEntity):
    """Base class for Teslemetry vehicle metric sensors."""

    entity_description: TeslemetrySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetrySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(
            data, description.key, description.timestamp_key, description.streaming_key
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        if self.has():
            self._attr_native_value = self.entity_description.value_fn(self._value)
        else:
            self._attr_native_value = None

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the sensor."""
        self._attr_native_value = self.entity_description.value_fn(value)


class TeslemetryVehicleTimeSensorEntity(TeslemetryVehicleEntity, SensorEntity):
    """Base class for Teslemetry vehicle metric sensors."""

    entity_description: TeslemetrySensorEntityDescription
    _last_value: int | None = None

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetrySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _get_timestamp(value):
        return (
            ignore_variance(
                func=lambda value: dt_util.now() + timedelta(minutes=value),
                ignored_variance=timedelta(minutes=1),
            ),
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_available = self._value is not None and self._value > 0

        if (value := self._value) == self._last_value:
            # No change
            return
        self._last_value = value
        if isinstance(value, int | float):
            # value = self._get_timestamp(value)
            value = dt_util.now() + timedelta(minutes=value)
        self.native_value = value

    def _async_value_from_stream(self, value) -> None:
        self._attr_available = True
        self._attr_native_value = dt_util.now() + timedelta(minutes=int(value))


class TeslemetryEnergyLiveSensorEntity(TeslemetryEnergyLiveEntity, SensorEntity):
    """Base class for Teslemetry energy site metric sensors."""

    entity_description: TeslemetrySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_available = not self.exactly(None)
        self._attr_native_value = self._value


class TeslemetryWallConnectorSensorEntity(TeslemetryWallConnectorEntity, SensorEntity):
    """Base class for Teslemetry energy site metric sensors."""

    entity_description: TeslemetrySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        din: str,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(
            data,
            din,
            description.key,
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_available = not self.exactly(None)
        self._attr_native_value = self._value


class TeslemetryEnergyInfoSensorEntity(TeslemetryEnergyInfoEntity, SensorEntity):
    """Base class for Teslemetry energy site metric sensors."""

    entity_description: TeslemetrySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_available = not self.exactly(None)
        self._attr_native_value = self._value
