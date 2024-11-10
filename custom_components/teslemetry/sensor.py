"""Sensor platform for Teslemetry integration."""

from __future__ import annotations

from tesla_fleet_api.const import TelemetryField
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import chain
from typing import cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    RestoreSensor,
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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util
from homeassistant.util.variance import ignore_variance

from .const import TeslemetryState, TeslemetryTimestamp, MODELS, ENERGY_HISTORY_FIELDS
from .entity import (
    TeslemetryEnergyInfoEntity,
    TeslemetryEnergyLiveEntity,
    TeslemetryVehicleEntity,
    TeslemetryVehicleStreamEntity,
    TeslemetryWallConnectorEntity,
    TeslemetryEnergyHistoryEntity,
)
from .models import TeslemetryEnergyData, TeslemetryVehicleData
from .helpers import auto_type, ignore_drop

ChargeStates = {
    "Starting": "starting",
    "Charging": "charging",
    "Stopped": "stopped",
    "Complete": "complete",
    "Disconnected": "disconnected",
    "NoPower": "no_power",
    "Idle": "stopped",  # streaming
    "QualifyLineConfig": "starting",  # streaming
    "Enable": "charging",  # streaming
}

WallConnectorStates = {
    0: "booting",
    1: "charging",
    2: "not_connected",
    4: "connected",
    5: "scheduled",
    6: "negotiating",  # unseen
    7: "error",  # unseen
    8: "charging_finished",  # seen, unconfirmed
    9: "waiting_car",  # unseen
    10: "charging_reduced",  # unseen
}

ShiftStates = {"P": "p", "D": "d", "R": "r", "N": "n"}

@dataclass(frozen=True, kw_only=True)
class TeslemetrySensorEntityDescription(SensorEntityDescription):
    """Describes Teslemetry Sensor entity."""

    value_fn: Callable[[StateType], StateType | datetime] = lambda x: x
    available_fn: Callable[[StateType], StateType | datetime] = lambda x: x is not None
    streaming_key: TelemetryField | None = None
    timestamp_key: TeslemetryTimestamp | None = None


VEHICLE_DESCRIPTIONS: tuple[TeslemetrySensorEntityDescription, ...] = (
    TeslemetrySensorEntityDescription(
        key="charge_state_charging_state",
        streaming_key=TelemetryField.CHARGE_STATE,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        options=list(set(ChargeStates.values())),
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
        suggested_display_precision=0,
        value_fn=lambda x: float(x),
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_usable_battery_level",
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charge_energy_added",
        streaming_key=TelemetryField.AC_CHARGING_ENERGY_IN,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        value_fn=ignore_drop(),
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_power",
        streaming_key=TelemetryField.AC_CHARGING_POWER,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        value_fn=lambda x: float(x),
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_voltage",
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_actual_current",
        streaming_key=TelemetryField.CHARGE_AMPS,
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
        entity_registry_enabled_default=False,
        value_fn=lambda value: value or 0,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_power",
        timestamp_key=TeslemetryTimestamp.DRIVE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda value: value or 0,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_shift_state",
        streaming_key=TelemetryField.GEAR,
        timestamp_key=TeslemetryTimestamp.DRIVE_STATE,
        options=list(ShiftStates.values()),
        device_class=SensorDeviceClass.ENUM,
        value_fn=lambda x: ShiftStates.get(str(x), "p"),
        available_fn=lambda x: True,
        entity_registry_enabled_default=False,
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
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_fl",
        streaming_key=TelemetryField.TPMS_PRESSURE_FL,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_fr",
        streaming_key=TelemetryField.TPMS_PRESSURE_FR,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_rl",
        streaming_key=TelemetryField.TPMS_PRESSURE_RL,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_rr",
        streaming_key=TelemetryField.TPMS_PRESSURE_RR,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_inside_temp",
        streaming_key=TelemetryField.INSIDE_TEMP,
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_outside_temp",
        streaming_key=TelemetryField.OUTSIDE_TEMP,
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_driver_temp_setting",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_passenger_temp_setting",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_traffic_minutes_delay",
        timestamp_key=TeslemetryTimestamp.DRIVE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_energy_at_arrival",
        timestamp_key=TeslemetryTimestamp.DRIVE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_miles_to_arrival",
        streaming_key=TelemetryField.MILES_TO_ARRIVAL,
        timestamp_key=TeslemetryTimestamp.DRIVE_STATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
    ),
    TeslemetrySensorEntityDescription(
        # This entity isnt allowed in core
        key="charge_state_minutes_to_full_charge",
        streaming_key=TelemetryField.TIME_TO_FULL_CHARGE,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        available_fn=lambda x: x is not None and x > 0,
    ),
    TeslemetrySensorEntityDescription(
        # This entity isnt allowed in core
        key="drive_state_active_route_minutes_to_arrival",
        streaming_key=TelemetryField.MINUTES_TO_ARRIVAL,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_fl",
        streaming_key=TelemetryField.TPMS_LAST_SEEN_PRESSURE_TIME_FL,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_fr",
        streaming_key=TelemetryField.TPMS_LAST_SEEN_PRESSURE_TIME_FR,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_rl",
        streaming_key=TelemetryField.TPMS_LAST_SEEN_PRESSURE_TIME_RL,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_rr",
        streaming_key=TelemetryField.TPMS_LAST_SEEN_PRESSURE_TIME_RR,
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_config_roof_color",
        streaming_key=TelemetryField.ROOF_COLOR,
        timestamp_key=TeslemetryTimestamp.VEHICLE_CONFIG,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_scheduled_charging_mode",
        streaming_key=TelemetryField.SCHEDULED_CHARGING_MODE,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_scheduled_charging_start_time",
        streaming_key=TelemetryField.SCHEDULED_CHARGING_START_TIME,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_scheduled_departure_time",
        streaming_key=TelemetryField.SCHEDULED_DEPARTURE_TIME,
        timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_config_exterior_color",
        streaming_key=TelemetryField.EXTERIOR_COLOR,
        timestamp_key=TeslemetryTimestamp.VEHICLE_CONFIG,
        entity_registry_enabled_default=False,
    ),
)


@dataclass(frozen=True, kw_only=True)
class TeslemetryTimeEntityDescription(SensorEntityDescription):
    """Describes Teslemetry Sensor entity."""

    variance: int = 60
    streaming_key: TelemetryField | None = None
    timestamp_key: TeslemetryTimestamp | None = None


VEHICLE_TIME_DESCRIPTIONS: tuple[TeslemetryTimeEntityDescription, ...] = (
    TeslemetryTimeEntityDescription(
        key="charge_state_minutes_to_full_charge",
        streaming_key=TelemetryField.TIME_TO_FULL_CHARGE,
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


@dataclass(frozen=True, kw_only=True)
class TeslemetryStreamSensorEntityDescription(SensorEntityDescription):
    """Describes Teslemetry Sensor entity."""

    value_fn: Callable[[StateType], StateType] = lambda x: auto_type(x)


VEHICLE_STREAM_DESCRIPTIONS: tuple[TeslemetryStreamSensorEntityDescription, ...] = (
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.BMS_STATE,
        entity_registry_enabled_default=False,
        value_fn=lambda x: x,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.BRAKE_PEDAL_POS,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.BRICK_VOLTAGE_MAX,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_registry_enabled_default=False,
        value_fn=lambda x: float(x),
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.BRICK_VOLTAGE_MIN,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_registry_enabled_default=False,
        value_fn=lambda x: float(x),
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.CAR_TYPE,
        entity_registry_enabled_default=False,
        value_fn=lambda x: x,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.CHARGE_CURRENT_REQUEST_MAX,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_registry_enabled_default=False,
        value_fn=lambda x: int(x),
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.CHARGE_PORT,
        entity_registry_enabled_default=False,
        value_fn=lambda x: x,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.CRUISE_FOLLOW_DISTANCE,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.CRUISE_SET_SPEED,
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,  # Might be dynamic
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.CRUISE_STATE,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DC_CHARGING_ENERGY_IN,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        value_fn=ignore_drop(),
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DC_CHARGING_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DC_DC_ENABLE,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DESTINATION_LOCATION,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_AXLE_SPEED_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_AXLE_SPEED_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_AXLE_SPEED_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_AXLE_SPEED_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_HEATSINK_TF,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=0,
        value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_HEATSINK_TR,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=0,
        value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_HEATSINK_TREL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=0,
        value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_HEATSINK_TRER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=0,
        value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_MOTOR_CURRENT_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_MOTOR_CURRENT_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_MOTOR_CURRENT_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_MOTOR_CURRENT_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_SLAVE_TORQUE_CMD,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_STATE_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_STATE_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_STATE_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_STATE_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_STATOR_TEMP_F,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=0,
        value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_STATOR_TEMP_R,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=0,
        value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_STATOR_TEMP_REL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=0,
        value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_STATOR_TEMP_RER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=0,
        value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_TORQUE_ACTUAL_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_TORQUE_ACTUAL_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_TORQUE_ACTUAL_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_TORQUE_ACTUAL_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_TORQUEMOTOR,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_V_BAT_F,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        suggested_display_precision=1,
        value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_V_BAT_R,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        suggested_display_precision=1,
        value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_V_BAT_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DI_V_BAT_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DOOR_STATE,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DRIVE_RAIL,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DRIVER_SEAT_BELT,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.DRIVER_SEAT_OCCUPIED,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.EMERGENCY_LANE_DEPARTURE_AVOIDANCE,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.ENERGY_REMAINING,
        value_fn=lambda x: float(x),
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.FAST_CHARGER_PRESENT,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.FORWARD_COLLISION_WARNING,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.GPS_HEADING,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.GPS_STATE,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.GUEST_MODE_ENABLED,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.GUEST_MODE_MOBILE_ACCESS_STATE,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.HVIL,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.ISOLATION_RESISTANCE,
        value_fn=lambda x: float(x),
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.LANE_DEPARTURE_AVOIDANCE,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.LATERAL_ACCELERATION,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.LIFETIME_ENERGY_GAINED_REGEN,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.LIFETIME_ENERGY_USED,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.LIFETIME_ENERGY_USED_DRIVE,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.LONGITUDINAL_ACCELERATION,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.MODULE_TEMP_MAX,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=lambda x: float(x),
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.MODULE_TEMP_MIN,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=lambda x: float(x),
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.NOT_ENOUGH_POWER_TO_HEAT,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.NUM_BRICK_VOLTAGE_MAX,
        entity_registry_enabled_default=False,
        value_fn=lambda x: x,  # Number is not a measurement
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.NUM_BRICK_VOLTAGE_MIN,
        entity_registry_enabled_default=False,
        value_fn=lambda x: x,  # Number is not a measurement
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.NUM_MODULE_TEMP_MAX,
        entity_registry_enabled_default=False,
        value_fn=lambda x: x,  # Number is not a measurement
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.NUM_MODULE_TEMP_MIN,
        entity_registry_enabled_default=False,
        value_fn=lambda x: x,  # Number is not a measurement
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.ORIGIN_LOCATION,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.PACK_CURRENT,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=lambda x: float(x),
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.PACK_VOLTAGE,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda x: float(x),
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.PAIRED_PHONE_KEY_AND_KEY_FOB_QTY,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=lambda x: int(x),
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.PASSENGER_SEAT_BELT,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.PEDAL_POSITION,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.PIN_TO_DRIVE_ENABLED,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.RATED_RANGE,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.ROUTE_LINE,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.ROUTE_LAST_UPDATED,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.SENTRY_MODE,
        device_class=SensorDeviceClass.ENUM,
        options=["Off","Armed", "Idle", "Aware"],
        entity_registry_enabled_default=False,
        value_fn=lambda x: x,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.SOC,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.SPEED_LIMIT_WARNING,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.SUPERCHARGER_SESSION_TRIP_PLANNER,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.TRIM,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.VEHICLE_NAME,
        entity_registry_enabled_default=False,
    ),
    TeslemetryStreamSensorEntityDescription(
        key=TelemetryField.VERSION,
        entity_registry_enabled_default=False,
    ),
)


@dataclass(frozen=True, kw_only=True)
class TeslemetryEnergySensorEntityDescription(SensorEntityDescription):
    """Describes Teslemetry Sensor entity."""

    value_fn: Callable[[StateType], StateType | datetime] = lambda x: x

ENERGY_LIVE_DESCRIPTIONS: tuple[TeslemetryEnergySensorEntityDescription, ...] = (
    TeslemetryEnergySensorEntityDescription(
        key="grid_status",
    ),
    TeslemetryEnergySensorEntityDescription(
        key="solar_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    TeslemetryEnergySensorEntityDescription(
        # Tesla may have removed this from the API
        key="energy_left",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryEnergySensorEntityDescription(
        # Tesla may have removed this from the API
        key="total_pack_energy",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="percentage_charged",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        suggested_display_precision=2,
        value_fn=lambda value: value or 0,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="battery_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="load_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="grid_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="grid_services_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="generator_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="island_status",
        device_class=SensorDeviceClass.ENUM,
        options=[
            "on_grid",
            "off_grid",
            "off_grid_intentional",
            "off_grid_unintentional",
            "island_status_unknown",
        ]
    ),
)


WALL_CONNECTOR_DESCRIPTIONS: tuple[
    TeslemetryEnergySensorEntityDescription, ...
] = (
    TeslemetryEnergySensorEntityDescription(
        key="wall_connector_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        options=list(WallConnectorStates.values()),
        device_class=SensorDeviceClass.ENUM,
        value_fn=lambda value: WallConnectorStates.get(cast(str, value)),
    ),
    TeslemetryEnergySensorEntityDescription(
        key="wall_connector_fault_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryEnergySensorEntityDescription(
        key="wall_connector_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.POWER,
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


ENERGY_HISTORY_DESCRIPTIONS: tuple[TeslemetryEnergySensorEntityDescription, ...] = tuple(
    TeslemetryEnergySensorEntityDescription(
        key=key,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=(key.startswith("total") or key=="grid_energy_imported"),
        value_fn=lambda x: x.get(key, 0),
    ) for key in ENERGY_HISTORY_FIELDS
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry sensor platform from a config entry."""

    async_add_entities(
        chain(
            (  # Add vehicles
                TeslemetryVehicleSensorEntity(vehicle, description)
                for vehicle in entry.runtime_data.vehicles
                for description in VEHICLE_DESCRIPTIONS
            ),
            (  # Add vehicles time sensors
                TeslemetryVehicleTimeSensorEntity(vehicle, description)
                for vehicle in entry.runtime_data.vehicles
                for description in VEHICLE_TIME_DESCRIPTIONS
            ),
            (  # Add vehicle streaming
                TeslemetryStreamSensorEntity(vehicle, description)
                for vehicle in entry.runtime_data.vehicles
                for description in VEHICLE_STREAM_DESCRIPTIONS
            ),
            (  # Add energy site live
                TeslemetryEnergyLiveSensorEntity(energysite, description)
                for energysite in entry.runtime_data.energysites
                for description in ENERGY_LIVE_DESCRIPTIONS
                if description.key in energysite.live_coordinator.data
            ),
            (  # Add wall connectors
                TeslemetryWallConnectorSensorEntity(energysite, din, description)
                for energysite in entry.runtime_data.energysites
                for din in energysite.live_coordinator.data.get("wall_connectors", {})
                for description in WALL_CONNECTOR_DESCRIPTIONS
            ),
            (  # Add wall connector connected vehicle
                TeslemetryWallConnectorVehicleSensorEntity(
                    energysite, din, entry.runtime_data.vehicles
                )
                for energysite in entry.runtime_data.energysites
                for din in energysite.live_coordinator.data.get("wall_connectors", {})
            ),
            (  # Add energy site info
                TeslemetryEnergyInfoSensorEntity(energysite, description)
                for energysite in entry.runtime_data.energysites
                for description in ENERGY_INFO_DESCRIPTIONS
                if description.key in energysite.info_coordinator.data
            ),
            (  # Add energy history sensor
                TeslemetryEnergyHistorySensorEntity(energysite, description)
                for energysite in entry.runtime_data.energysites
                for description in ENERGY_HISTORY_DESCRIPTIONS
                if energysite.history_coordinator is not None
            ),
            (  # Add alert event sensor
                TeslemetryVehicleEventEntity(vehicle, "alerts")
                for vehicle in entry.runtime_data.vehicles
            ),
            (  # Add error event sensor
                TeslemetryVehicleEventEntity(vehicle, "errors")
                for vehicle in entry.runtime_data.vehicles
            )
        )
    )


class TeslemetryVehicleSensorEntity(TeslemetryVehicleEntity, RestoreSensor):
    """Base class for Teslemetry vehicle metric sensors."""

    entity_description: TeslemetrySensorEntityDescription
    streaming_gap = 60000

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

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if self.coordinator.data.get('state') == TeslemetryState.OFFLINE:

            if (sensor_data := await self.async_get_last_sensor_data()) is not None and not self.coordinator.updated_once:
                self._attr_native_value = sensor_data.native_value

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""

        if self.entity_description.available_fn(self._value):
            self._attr_available = True
            self._attr_native_value = self.entity_description.value_fn(self._value)
        else:
            self._attr_available = False
            self._attr_native_value = None


    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        self._attr_available = True
        if value := auto_type(value) is not None:
            self._attr_native_value = self.entity_description.value_fn(value)


class TeslemetryVehicleTimeSensorEntity(TeslemetryVehicleEntity, SensorEntity):
    """Base class for Teslemetry vehicle metric sensors."""

    entity_description: TeslemetryTimeEntityDescription
    _last_value: int | None = None

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetryTimeEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._get_timestamp = ignore_variance(
            func=lambda value: dt_util.utcnow() + timedelta(minutes=value),
            ignored_variance=timedelta(minutes=1),
        )

        super().__init__(data, description.key)
        self._attr_translation_key = f"{self.entity_description.key}_timestamp"
        self._attr_unique_id = f"{data.vin}-{description.key}_timestamp"

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""

        self._attr_available = self._value is not None and self._value > 0

        if (value := self._value) == self._last_value:
            # No change
            return
        self._last_value = value
        if isinstance(value, int | float):
            self._attr_native_value = self._get_timestamp(value)
        else:
            self._attr_native_value = None

    def _async_value_from_stream(self, value) -> None:
        self._attr_available = True
        self._attr_native_value = self._get_timestamp(int(value))


class TeslemetryStreamSensorEntity(TeslemetryVehicleStreamEntity, RestoreSensor):
    """Base class for Teslemetry vehicle streaming sensors."""

    entity_description: TeslemetryStreamSensorEntityDescription

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetryStreamSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        if (sensor_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = sensor_data.native_value

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        self._attr_available = self.stream.connected
        if (value is None):
            self._attr_native_value = None
        else:
            self._attr_native_value = self.entity_description.value_fn(value)


class TeslemetryEnergyLiveSensorEntity(TeslemetryEnergyLiveEntity, SensorEntity):
    """Base class for Teslemetry energy site metric sensors."""

    entity_description: TeslemetryEnergySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: TeslemetryEnergySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_available = not self.exactly(None)
        self._attr_native_value = self.entity_description.value_fn(self._value)


class TeslemetryWallConnectorSensorEntity(TeslemetryWallConnectorEntity, SensorEntity):
    """Base class for Teslemetry Wall Connector sensors."""

    entity_description: TeslemetryEnergySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        din: str,
        description: TeslemetryEnergySensorEntityDescription,
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

        if not self.has:
            return

        self._attr_available = not self.exactly(None)
        self._attr_native_value = self.entity_description.value_fn(self._value)


class TeslemetryWallConnectorVehicleSensorEntity(
    TeslemetryWallConnectorEntity, SensorEntity
):
    """Entity for Teslemetry wall connector vehicle sensors."""

    entity_description: TeslemetryEnergySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        din: str,
        vehicles: list[TeslemetryVehicleData],
    ) -> None:
        """Initialize the sensor."""
        self._vehicles = vehicles
        super().__init__(
            data,
            din,
            "vin",
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""

        if not self.has:
            return

        if self.exactly(None):
            self._attr_native_value = "None"
            self._attr_extra_state_attributes = {}
            return

        value = self._value
        for vehicle in self._vehicles:
            if vehicle.vin == value:
                self._attr_native_value = vehicle.device["name"]
                self._attr_extra_state_attributes = {
                    "vin": vehicle.vin,
                    "model": vehicle.device["model"],
                }
                return
        self._attr_native_value = value
        self._attr_extra_state_attributes = {
            "vin": value,
            "model": MODELS.get(value[3]),
        }


class TeslemetryEnergyInfoSensorEntity(TeslemetryEnergyInfoEntity, SensorEntity):
    """Base class for Teslemetry energy site metric sensors."""

    entity_description: SensorEntityDescription

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


class TeslemetryEnergyHistorySensorEntity(TeslemetryEnergyHistoryEntity, SensorEntity):
    """Base class for Teslemetry energy site metric sensors."""

    entity_description: SensorEntityDescription

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
        self._attr_native_value = self._value


class TeslemetryVehicleEventEntity(RestoreSensor):
    """Parent class for Teslemetry Vehicle Stream entities."""

    _attr_has_entity_name = True

    def __init__(
        self, data: TeslemetryVehicleData, key: str
    ) -> None:
        """Initialize common aspects of a Teslemetry entity."""

        self.key = key
        self._attr_translation_key = f"event_{key}"
        self.stream = data.stream
        self.vin = data.vin

        self._attr_unique_id = f"{data.vin}-event_{key}"
        self._attr_device_info = data.device

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        if (sensor_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = sensor_data.native_value

        if self.stream.server:
            self.async_on_remove(
                self.stream.async_add_listener(
                    self._handle_stream_update,
                    {"vin": self.vin, self.key: None},
                )
            )

    def _handle_stream_update(self, data: dict[str, list]) -> None:
        """Handle updated data from the stream."""
        self._attr_available = self.stream.connected
        self._attr_native_value = data[self.key][0]['name']
        self.async_write_ha_state()
