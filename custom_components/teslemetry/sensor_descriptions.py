"""Sensor descriptions for Teslemetry integration."""

from __future__ import annotations

from teslemetry_stream import TelemetryFields
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
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
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .const import TeslemetryPollingKeys, ENERGY_HISTORY_FIELDS

ChargeStates = {
    "Starting": "starting",
    "Charging": "charging",
    "Stopped": "stopped",
    "Complete": "complete",
    "Disconnected": "disconnected",
    "NoPower": "no_power",
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

    polling_parent: TeslemetryPollingKeys | None = None
    polling_value_fn: Callable[[StateType], StateType | datetime] = lambda x: x
    polling_available_fn: Callable[[StateType], StateType | datetime] = lambda x: x is not None
    streaming_key: TelemetryFields | None = None
    streaming_value_fn: Callable[[StateType], StateType | datetime] = lambda x: x
    streaming_firmware: str = "2024.26"


VEHICLE_DESCRIPTIONS: tuple[TeslemetrySensorEntityDescription, ...] = (
    TeslemetrySensorEntityDescription(
        key="charge_state_charging_state",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.DETAILED_CHARGE_STATE,
        polling_value_fn=lambda value: ChargeStates.get(cast(str, value)),
        streaming_value_fn=lambda value: ChargeStates.get(cast(str, value)),

        options=list(ChargeStates.values()),
        device_class=SensorDeviceClass.ENUM,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_battery_level",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.BATTERY_LEVEL,
        state_class=SensorStateClass.MEASUREMENT,

        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_usable_battery_level",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charge_energy_added",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.AC_CHARGING_ENERGY_IN,

        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_power",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.AC_CHARGING_POWER,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_voltage",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_actual_current",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.CHARGE_AMPS,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charge_rate",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.MILES_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_conn_charge_cable",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.CHARGING_CABLE_TYPE,

        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_fast_charger_type",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.FAST_CHARGER_TYPE,

        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_battery_range",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_est_battery_range",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.EST_BATTERY_RANGE,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        entity_registry_enabled_default=True,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_ideal_battery_range",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.IDEAL_BATTERY_RANGE,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_speed",
        streaming_key=TelemetryFields.VEHICLE_SPEED,
        polling_parent=TeslemetryPollingKeys.DRIVE_STATE,
        polling_value_fn=lambda value: value or 0,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.MILES_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        entity_registry_enabled_default=False,

    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_power",
        polling_parent=TeslemetryPollingKeys.DRIVE_STATE,
        polling_value_fn=lambda value: value or 0,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_shift_state",
        polling_parent=TeslemetryPollingKeys.DRIVE_STATE,
        streaming_key=TelemetryFields.GEAR,
        polling_value_fn=lambda x: ShiftStates.get(str(x), "p"),
        polling_available_fn=lambda x: True,
        streaming_value_fn=lambda x: ShiftStates.get(str(x)),

        options=list(ShiftStates.values()),
        device_class=SensorDeviceClass.ENUM,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_odometer",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,
        streaming_key=TelemetryFields.ODOMETER,

        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_fl",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,
        streaming_key=TelemetryFields.TPMS_PRESSURE_FL,

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
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,
        streaming_key=TelemetryFields.TPMS_PRESSURE_FR,

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
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,
        streaming_key=TelemetryFields.TPMS_PRESSURE_RL,

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
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,
        streaming_key=TelemetryFields.TPMS_PRESSURE_RR,

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
        polling_parent=TeslemetryPollingKeys.CLIMATE_STATE,
        streaming_key=TelemetryFields.INSIDE_TEMP,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_outside_temp",
        polling_parent=TeslemetryPollingKeys.CLIMATE_STATE,
        streaming_key=TelemetryFields.OUTSIDE_TEMP,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_driver_temp_setting",
        polling_parent=TeslemetryPollingKeys.CLIMATE_STATE,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_passenger_temp_setting",
        polling_parent=TeslemetryPollingKeys.CLIMATE_STATE,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_traffic_minutes_delay",
        polling_parent=TeslemetryPollingKeys.DRIVE_STATE,
        streaming_key=TelemetryFields.ROUTE_TRAFFIC_MINUTES_DELAY,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_energy_at_arrival",
        polling_parent=TeslemetryPollingKeys.DRIVE_STATE,
        streaming_key=TelemetryFields.EXPECTED_ENERGY_PERCENT_AT_TRIP_ARRIVAL,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=1
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_miles_to_arrival",
        polling_parent=TeslemetryPollingKeys.DRIVE_STATE,
        streaming_key=TelemetryFields.MILES_TO_ARRIVAL,

        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
    ),
    TeslemetrySensorEntityDescription(
        # This entity isnt allowed in core
        key="charge_state_minutes_to_full_charge",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.TIME_TO_FULL_CHARGE,
        polling_available_fn=lambda x: x is not None and float(x) > 0,

        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        # This entity isnt allowed in core
        key="drive_state_active_route_minutes_to_arrival",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.MINUTES_TO_ARRIVAL,

        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_fl",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,
        streaming_key=TelemetryFields.TPMS_LAST_SEEN_PRESSURE_TIME_FL,
        polling_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),

        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_fr",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,
        streaming_key=TelemetryFields.TPMS_LAST_SEEN_PRESSURE_TIME_FR,
        polling_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),

        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_rl",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,
        streaming_key=TelemetryFields.TPMS_LAST_SEEN_PRESSURE_TIME_RL,
        polling_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),

        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_rr",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,
        streaming_key=TelemetryFields.TPMS_LAST_SEEN_PRESSURE_TIME_RR,
        polling_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),

        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_config_roof_color",
        polling_parent=TeslemetryPollingKeys.VEHICLE_CONFIG,
        streaming_key=TelemetryFields.ROOF_COLOR,

        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_scheduled_charging_mode",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.SCHEDULED_CHARGING_MODE,

        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_scheduled_charging_start_time",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        polling_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        streaming_key=TelemetryFields.SCHEDULED_CHARGING_START_TIME,
        streaming_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),

        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_scheduled_departure_time",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        polling_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),
        streaming_key=TelemetryFields.SCHEDULED_DEPARTURE_TIME,
        streaming_value_fn=lambda x: dt_util.utc_from_timestamp(int(x)),

        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_config_exterior_color",
        polling_parent=TeslemetryPollingKeys.VEHICLE_CONFIG,
        streaming_key=TelemetryFields.EXTERIOR_COLOR,

        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="bms_state",
        streaming_key=TelemetryFields.BMS_STATE,

        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: x,
    ),
    TeslemetrySensorEntityDescription(
        key="brake_pedal_position",
        streaming_key=TelemetryFields.BRAKE_PEDAL_POS,

        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="brick_voltage_max",
        streaming_key=TelemetryFields.BRICK_VOLTAGE_MAX,

        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="brick_voltage_min",
        streaming_key=TelemetryFields.BRICK_VOLTAGE_MIN,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: float(x),
    ),
    TeslemetrySensorEntityDescription(
        key="car_type",
        streaming_key=TelemetryFields.CAR_TYPE,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: x,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_current_request_max",
        streaming_key=TelemetryFields.CHARGE_CURRENT_REQUEST_MAX,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: int(x),
    ),
    TeslemetrySensorEntityDescription(
        key="charge_port",
        streaming_key=TelemetryFields.CHARGE_PORT,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: x,
    ),
    TeslemetrySensorEntityDescription(
        key="cruise_follow_distance",
        streaming_key=TelemetryFields.CRUISE_FOLLOW_DISTANCE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="cruise_set_speed",
        streaming_key=TelemetryFields.CRUISE_SET_SPEED,
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,  # Might be dynamic
    ),
    TeslemetrySensorEntityDescription(
        key="dc_charging_engery_in",
        streaming_key=TelemetryFields.DC_CHARGING_ENERGY_IN,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="dc_charging_power",
        streaming_key=TelemetryFields.DC_CHARGING_POWER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="dc_dc_enable",
        streaming_key=TelemetryFields.DC_DC_ENABLE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="destination_location",
        streaming_key=TelemetryFields.DESTINATION_LOCATION,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_axle_speed_front",
        streaming_key=TelemetryFields.DI_AXLE_SPEED_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_axle_speed_rear",
        streaming_key=TelemetryFields.DI_AXLE_SPEED_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_axle_speed_rear_left",
        streaming_key=TelemetryFields.DI_AXLE_SPEED_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_axle_speed_rear_right",
        streaming_key=TelemetryFields.DI_AXLE_SPEED_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_heatsink_temp_front",
        streaming_key=TelemetryFields.DI_HEATSINK_TF,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_heatsink_temp_rear",
        streaming_key=TelemetryFields.DI_HEATSINK_TR,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_heatsink_temp_rear_left",
        streaming_key=TelemetryFields.DI_HEATSINK_TREL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_heatsink_temp_rear_right",
        streaming_key=TelemetryFields.DI_HEATSINK_TRER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_motor_current_front",
        streaming_key=TelemetryFields.DI_MOTOR_CURRENT_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_motor_current_rear",
        streaming_key=TelemetryFields.DI_MOTOR_CURRENT_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_motor_current_rear_left",
        streaming_key=TelemetryFields.DI_MOTOR_CURRENT_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_motor_current_rear_right",
        streaming_key=TelemetryFields.DI_MOTOR_CURRENT_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_salve_torque_command",
        streaming_key=TelemetryFields.DI_SLAVE_TORQUE_CMD,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_state_front",
        streaming_key=TelemetryFields.DI_STATE_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_state_rear",
        streaming_key=TelemetryFields.DI_STATE_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_state_rear_left",
        streaming_key=TelemetryFields.DI_STATE_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_state_rear_right",
        streaming_key=TelemetryFields.DI_STATE_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_stator_temp_front",
        streaming_key=TelemetryFields.DI_STATOR_TEMP_F,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_stator_temp_rear",
        streaming_key=TelemetryFields.DI_STATOR_TEMP_R,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        streaming_value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_stator_temp_rear_left",
        streaming_key=TelemetryFields.DI_STATOR_TEMP_REL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        streaming_value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_stator_temp_rear_right",
        streaming_key=TelemetryFields.DI_STATOR_TEMP_RER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        streaming_value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_actual_front",
        streaming_key=TelemetryFields.DI_TORQUE_ACTUAL_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_actual_rear",
        streaming_key=TelemetryFields.DI_TORQUE_ACTUAL_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_actual_rear_left",
        streaming_key=TelemetryFields.DI_TORQUE_ACTUAL_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_actual_rear_right",
        streaming_key=TelemetryFields.DI_TORQUE_ACTUAL_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_motor",
        streaming_key=TelemetryFields.DI_TORQUEMOTOR,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_voltage_battery_front",
        streaming_key=TelemetryFields.DI_V_BAT_F,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        suggested_display_precision=1,
        streaming_value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_voltage_battery_rear",
        streaming_key=TelemetryFields.DI_V_BAT_R,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        suggested_display_precision=1,
        streaming_value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_voltage_battery_rear_left",
        streaming_key=TelemetryFields.DI_V_BAT_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_voltage_battery_rear_right",
        streaming_key=TelemetryFields.DI_V_BAT_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="door_state",
        streaming_key=TelemetryFields.DOOR_STATE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_rail",
        streaming_key=TelemetryFields.DRIVE_RAIL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="driver_seat_belt",
        streaming_key=TelemetryFields.DRIVER_SEAT_BELT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="driver_seat_occupied",
        streaming_key=TelemetryFields.DRIVER_SEAT_OCCUPIED,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="emergency_lane_departure_avoidance",
        streaming_key=TelemetryFields.EMERGENCY_LANE_DEPARTURE_AVOIDANCE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="energy_remaining",
        streaming_key=TelemetryFields.ENERGY_REMAINING,
        streaming_value_fn=lambda x: float(x),

        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="fast_charger_present",
        streaming_key=TelemetryFields.FAST_CHARGER_PRESENT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="forward_collision_warning",
        streaming_key=TelemetryFields.FORWARD_COLLISION_WARNING,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="gps_heading",
        streaming_key=TelemetryFields.GPS_HEADING,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="gps_state",
        streaming_key=TelemetryFields.GPS_STATE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="guest_mode_enabled",
        streaming_key=TelemetryFields.GUEST_MODE_ENABLED,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="guest_mode_mobile_access_state",
        streaming_key=TelemetryFields.GUEST_MODE_MOBILE_ACCESS_STATE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="hvil",
        streaming_key=TelemetryFields.HVIL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="isolation_resistance",
        streaming_key=TelemetryFields.ISOLATION_RESISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="lane_departure_avoidance",
        streaming_key=TelemetryFields.LANE_DEPARTURE_AVOIDANCE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="lateral_acceleration",
        streaming_key=TelemetryFields.LATERAL_ACCELERATION,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="lifetime_energy_gained_regen",
        streaming_key=TelemetryFields.LIFETIME_ENERGY_GAINED_REGEN,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="lifetime_energy_used",
        streaming_key=TelemetryFields.LIFETIME_ENERGY_USED,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="lifetime_energy_used_drive",
        streaming_key=TelemetryFields.LIFETIME_ENERGY_USED_DRIVE,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="longitudinal_acceleration",
        streaming_key=TelemetryFields.LONGITUDINAL_ACCELERATION,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="module_temp_max",
        streaming_key=TelemetryFields.MODULE_TEMP_MAX,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="module_temp_min",
        streaming_key=TelemetryFields.MODULE_TEMP_MIN,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="no_enough_power_to_heat",
        streaming_key=TelemetryFields.NOT_ENOUGH_POWER_TO_HEAT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="brick_number_voltage_max",
        streaming_key=TelemetryFields.NUM_BRICK_VOLTAGE_MAX,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="brick_number_voltage_min",
        streaming_key=TelemetryFields.NUM_BRICK_VOLTAGE_MIN,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: x,  # Number is not a measurement
    ),
    TeslemetrySensorEntityDescription(
        key="module_number_temp_max",
        streaming_key=TelemetryFields.NUM_MODULE_TEMP_MAX,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: x,  # Number is not a measurement
    ),
    TeslemetrySensorEntityDescription(
        key="module_number_temp_min",
        streaming_key=TelemetryFields.NUM_MODULE_TEMP_MIN,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: x,  # Number is not a measurement
    ),
    TeslemetrySensorEntityDescription(
        key="origin_location",
        streaming_key=TelemetryFields.ORIGIN_LOCATION,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="pack_current",
        streaming_key=TelemetryFields.PACK_CURRENT,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: float(x),
    ),
    TeslemetrySensorEntityDescription(
        key="pack_voltage",
        streaming_key=TelemetryFields.PACK_VOLTAGE,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: float(x),
    ),
    TeslemetrySensorEntityDescription(
        key="paired_key_quantity",
        streaming_key=TelemetryFields.PAIRED_PHONE_KEY_AND_KEY_FOB_QTY,
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: int(x),
    ),
    TeslemetrySensorEntityDescription(
        key="passenger_seat_belt",
        streaming_key=TelemetryFields.PASSENGER_SEAT_BELT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="pedal_position",
        streaming_key=TelemetryFields.PEDAL_POSITION,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="pin_to_drive_enabled",
        streaming_key=TelemetryFields.PIN_TO_DRIVE_ENABLED,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="rated_range",
        streaming_key=TelemetryFields.RATED_RANGE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="route_last_updated",
        streaming_key=TelemetryFields.ROUTE_LAST_UPDATED,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="sentry_mode",
        streaming_key=TelemetryFields.SENTRY_MODE,
        device_class=SensorDeviceClass.ENUM,
        options=["Off","Armed", "Idle", "Aware"],
        entity_registry_enabled_default=False,
        streaming_value_fn=lambda x: str(x).replace("SentryModeState",""),
    ),
    TeslemetrySensorEntityDescription(
        key="state_of_charge",
        streaming_key=TelemetryFields.SOC,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="speed_limit_warning",
        streaming_key=TelemetryFields.SPEED_LIMIT_WARNING,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="supercharger_session_trip_planner",
        streaming_key=TelemetryFields.SUPERCHARGER_SESSION_TRIP_PLANNER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="trim",
        streaming_key=TelemetryFields.TRIM,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_name",
        streaming_key=TelemetryFields.VEHICLE_NAME,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="center_display",
        streaming_key=TelemetryFields.CENTER_DISPLAY,
        options=[
          "Off",
          "Dim",
          "Accessory",
          "On",
          "Driving",
          "Charging",
          "Lock",
          "Sentry",
          "Dog",
          "Entertainment"
        ],
        streaming_value_fn=lambda x: str(x).replace("DisplayState",""),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="efficiency_package",
        streaming_key=TelemetryFields.EFFICIENCY_PACKAGE,
        entity_registry_enabled_default=False,
    ),
)

@dataclass(frozen=True, kw_only=True)
class TeslemetryTimeEntityDescription(SensorEntityDescription):
    """Describes Teslemetry Sensor entity."""

    variance: int = 60
    polling_parent: TeslemetryPollingKeys | None = None
    streaming_key: TelemetryFields | None = None


VEHICLE_TIME_DESCRIPTIONS: tuple[TeslemetryTimeEntityDescription, ...] = (
    TeslemetryTimeEntityDescription(
        key="charge_state_minutes_to_full_charge",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.TIME_TO_FULL_CHARGE,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryTimeEntityDescription(
        key="drive_state_active_route_minutes_to_arrival",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.MINUTES_TO_ARRIVAL,
        device_class=SensorDeviceClass.TIMESTAMP,
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
