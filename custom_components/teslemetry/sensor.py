"""Sensor platform for Teslemetry integration."""

from __future__ import annotations
from datetime import timedelta, datetime
from typing import Any

from teslemetry_stream import Signal, TeslemetryStream
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from homeassistant.components.sensor import (
    SensorEntity,
    RestoreSensor,
    SensorEntityDescription,
)
from homeassistant.components.sensor.const import (
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    DEGREE,
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
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from homeassistant.util.variance import ignore_variance

from . import TeslemetryConfigEntry
from .const import MODELS, ENERGY_HISTORY_FIELDS

from .entity import (
    TeslemetryEnergyInfoEntity,
    TeslemetryEnergyLiveEntity,
    TeslemetryVehicleEntity,
    TeslemetryVehicleStreamSingleEntity,
    TeslemetryWallConnectorEntity,
    TeslemetryEnergyHistoryEntity,
)
from .models import TeslemetryEnergyData, TeslemetryVehicleData, TeslemetryData
from .enums import (
    CableType,
    CarType,
    ChargePort,
    DetailedChargeState,
    FastCharger,
    FollowDistance,
    HvilStatus,
    PowershareState,
    PowershareStopReasonStatus,
    PowershareTypeStatus,
    ShiftState,
    ScheduledChargingMode,
    BMSState,
    ForwardCollisionSensitivity,
    GuestModeMobileAccess,
    LaneAssistLevel,
    SentryModeState,
    SpeedAssistLevel,
    DisplayState
)

WALL_CONNECTOR_STATES = {
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

def passNull(callable: Callable):
    """Dont call callable on null values."""
    def wrapper(value: StateType):
        if value is None:
            return None
        return callable(value)
    return wrapper

@dataclass(frozen=True, kw_only=True)
class TeslemetrySensorEntityDescription(SensorEntityDescription):
    """Describes Teslemetry Sensor entity."""

    polling: bool = False
    polling_value_fn: Callable[[StateType], StateType | datetime] = lambda x: x
    available_fn: Callable[[StateType], StateType | datetime] = lambda x: x is not None
    streaming_key: Signal | None = None
    streaming_value_fn: Callable[[StateType], StateType | datetime] = lambda x: x
    streaming_firmware: str = "2024.26"


VEHICLE_DESCRIPTIONS: tuple[TeslemetrySensorEntityDescription, ...] = (
    TeslemetrySensorEntityDescription(
        key="charge_state_charging_state",
        polling=True,
        streaming_key=Signal.DETAILED_CHARGE_STATE,
        polling_value_fn=DetailedChargeState.get,
        streaming_value_fn=DetailedChargeState.get,
        device_class=SensorDeviceClass.ENUM,
        options=DetailedChargeState.options
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_battery_level",
        polling=True,
        streaming_key=Signal.BATTERY_LEVEL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_usable_battery_level",
        polling=True,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charge_energy_added",
        polling=True,
        streaming_key=Signal.AC_CHARGING_ENERGY_IN,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_power",
        polling=True,
        streaming_key=Signal.AC_CHARGING_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_voltage",
        polling=True,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charger_actual_current",
        polling=True,
        streaming_key=Signal.CHARGE_AMPS,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_charge_rate",
        polling=True,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.MILES_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_conn_charge_cable",
        polling=True,
        polling_value_fn=CableType.get,
        streaming_key=Signal.CHARGING_CABLE_TYPE,
        streaming_value_fn=CableType.get,
        options=CableType.options,
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_fast_charger_type",
        polling=True,
        polling_value_fn=FastCharger.get,
        streaming_key=Signal.FAST_CHARGER_TYPE,
        streaming_value_fn=FastCharger.get,
        options=FastCharger.options,
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_battery_range",
        polling=True,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_est_battery_range",
        polling=True,
        streaming_key=Signal.EST_BATTERY_RANGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_ideal_battery_range",
        polling=True,
        streaming_key=Signal.IDEAL_BATTERY_RANGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_speed",
        streaming_key=Signal.VEHICLE_SPEED,
        polling=True,
        polling_value_fn=lambda value: value or 0,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.MILES_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_power",
        polling=True,
        polling_value_fn=lambda value: value or 0,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_shift_state",
        polling=True,
        streaming_key=Signal.GEAR,
        polling_value_fn=lambda x: ShiftState.get(x, "p"),
        available_fn=lambda x: True,
        streaming_value_fn=lambda x: ShiftState.get(x, "p"),
        options=ShiftState.options,
        device_class=SensorDeviceClass.ENUM,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_odometer",
        polling=True,
        streaming_key=Signal.ODOMETER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_fl",
        polling=True,
        streaming_key=Signal.TPMS_PRESSURE_FL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_fr",
        polling=True,
        streaming_key=Signal.TPMS_PRESSURE_FR,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_rl",
        polling=True,
        streaming_key=Signal.TPMS_PRESSURE_RL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_pressure_rr",
        polling=True,
        streaming_key=Signal.TPMS_PRESSURE_RR,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_inside_temp",
        polling=True,
        streaming_key=Signal.INSIDE_TEMP,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_outside_temp",
        polling=True,
        streaming_key=Signal.OUTSIDE_TEMP,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_driver_temp_setting",
        polling=True,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="climate_state_passenger_temp_setting",
        polling=True,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_traffic_minutes_delay",
        polling=True,
        streaming_key=Signal.ROUTE_TRAFFIC_MINUTES_DELAY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_energy_at_arrival",
        polling=True,
        streaming_key=Signal.EXPECTED_ENERGY_PERCENT_AT_TRIP_ARRIVAL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=1
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_active_route_miles_to_arrival",
        polling=True,
        streaming_key=Signal.MILES_TO_ARRIVAL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1
    ),
    TeslemetrySensorEntityDescription(
        # This entity isnt allowed in core
        key="charge_state_time_to_full_charge",
        polling=True,
        streaming_key=Signal.TIME_TO_FULL_CHARGE,
        available_fn=lambda x: x is not None and float(x) > 0,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        # This entity isnt allowed in core
        key="drive_state_active_route_minutes_to_arrival",
        polling=True,
        streaming_key=Signal.MINUTES_TO_ARRIVAL,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_fl",
        polling=True,
        streaming_key=Signal.TPMS_LAST_SEEN_PRESSURE_TIME_FL,
        polling_value_fn=passNull(lambda x: dt_util.utc_from_timestamp(int(x))),
        streaming_value_fn=passNull(lambda x: dt_util.utc_from_timestamp(int(x))),
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_fr",
        polling=True,
        streaming_key=Signal.TPMS_LAST_SEEN_PRESSURE_TIME_FR,
        polling_value_fn=passNull(lambda x: dt_util.utc_from_timestamp(int(x))),
        streaming_value_fn=passNull(lambda x: dt_util.utc_from_timestamp(int(x))),
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_rl",
        polling=True,
        streaming_key=Signal.TPMS_LAST_SEEN_PRESSURE_TIME_RL,
        polling_value_fn=passNull(lambda x: dt_util.utc_from_timestamp(int(x))),
        streaming_value_fn=passNull(lambda x: dt_util.utc_from_timestamp(int(x))),
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_state_tpms_last_seen_pressure_time_rr",
        polling=True,
        streaming_key=Signal.TPMS_LAST_SEEN_PRESSURE_TIME_RR,
        polling_value_fn=passNull(lambda x: dt_util.utc_from_timestamp(int(x))),
        streaming_value_fn=passNull(lambda x: dt_util.utc_from_timestamp(int(x))),
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_config_roof_color",
        polling=True,
        streaming_key=Signal.ROOF_COLOR,
        streaming_value_fn=lambda x: str(x).replace("RoofColor", ""),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_scheduled_charging_mode",
        polling=True,
        streaming_key=Signal.SCHEDULED_CHARGING_MODE,
        streaming_value_fn=ScheduledChargingMode.get,
        options=ScheduledChargingMode.options,
        device_class=SensorDeviceClass.ENUM,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_scheduled_charging_start_time",
        polling=True,
        polling_value_fn=passNull(lambda x: dt_util.utc_from_timestamp(int(x))),
        streaming_key=Signal.SCHEDULED_CHARGING_START_TIME,
        streaming_value_fn=passNull(lambda x: dt_util.utc_from_timestamp(int(x))),
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_state_scheduled_departure_time",
        polling=True,
        polling_value_fn=passNull(lambda x: dt_util.utc_from_timestamp(int(x))),
        streaming_key=Signal.SCHEDULED_DEPARTURE_TIME,
        streaming_value_fn=passNull(lambda x: dt_util.utc_from_timestamp(int(x))),
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_config_exterior_color",
        polling=True,
        streaming_key=Signal.EXTERIOR_COLOR,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="bms_state",
        streaming_key=Signal.BMS_STATE,
        streaming_value_fn=BMSState.get,
        options=BMSState.options,
        device_class=SensorDeviceClass.ENUM,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="brake_pedal_position",
        streaming_key=Signal.BRAKE_PEDAL_POS,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="brick_voltage_max",
        streaming_key=Signal.BRICK_VOLTAGE_MAX,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="brick_voltage_min",
        streaming_key=Signal.BRICK_VOLTAGE_MIN,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="car_type",
        streaming_key=Signal.CAR_TYPE,
        streaming_value_fn=CarType.get,
        options=CarType.options,
        device_class=SensorDeviceClass.ENUM,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_current_request_max",
        streaming_key=Signal.CHARGE_CURRENT_REQUEST_MAX,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
    ),
    TeslemetrySensorEntityDescription(
        key="charge_port",
        streaming_key=Signal.CHARGE_PORT,
        streaming_value_fn=ChargePort.get,
        options=ChargePort.options,
        device_class=SensorDeviceClass.ENUM,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="cruise_follow_distance",
        streaming_key=Signal.CRUISE_FOLLOW_DISTANCE,
        entity_registry_enabled_default=False,
        streaming_value_fn=FollowDistance.get,
        options=FollowDistance.options,
        device_class=SensorDeviceClass.ENUM,
    ),
    TeslemetrySensorEntityDescription(
        key="cruise_set_speed",
        streaming_key=Signal.CRUISE_SET_SPEED,
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,  # Might be dynamic
        suggested_display_precision=2,
    ),
    TeslemetrySensorEntityDescription(
        key="dc_charging_engery_in",
        streaming_key=Signal.DC_CHARGING_ENERGY_IN,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, #Unconfirmed
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
    ),
    TeslemetrySensorEntityDescription(
        key="dc_charging_power",
        streaming_key=Signal.DC_CHARGING_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT, #Unconfirmed
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
        suggested_display_precision=2,
    ),
    TeslemetrySensorEntityDescription(
        key="di_axle_speed_front",
        streaming_key=Signal.DI_AXLE_SPEED_F,
        entity_registry_enabled_default=False,
        suggested_display_precision=2,
    ),
    TeslemetrySensorEntityDescription(
        key="di_axle_speed_rear",
        streaming_key=Signal.DI_AXLE_SPEED_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_axle_speed_rear_left",
        streaming_key=Signal.DI_AXLE_SPEED_REL,
        entity_registry_enabled_default=False,
        suggested_display_precision=2,
    ),
    TeslemetrySensorEntityDescription(
        key="di_axle_speed_rear_right",
        streaming_key=Signal.DI_AXLE_SPEED_RER,
        entity_registry_enabled_default=False,
        suggested_display_precision=2,
    ),
    TeslemetrySensorEntityDescription(
        key="di_heatsink_temp_front",
        streaming_key=Signal.DI_HEATSINK_TF,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        streaming_value_fn=lambda x: float(x),
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_heatsink_temp_rear",
        streaming_key=Signal.DI_HEATSINK_TR,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_heatsink_temp_rear_left",
        streaming_key=Signal.DI_HEATSINK_TREL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_heatsink_temp_rear_right",
        streaming_key=Signal.DI_HEATSINK_TRER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_motor_current_front",
        streaming_key=Signal.DI_MOTOR_CURRENT_F,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
    ),
    TeslemetrySensorEntityDescription(
        key="di_motor_current_rear",
        streaming_key=Signal.DI_MOTOR_CURRENT_R,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
    ),
    TeslemetrySensorEntityDescription(
        key="di_motor_current_rear_left",
        streaming_key=Signal.DI_MOTOR_CURRENT_REL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
    ),
    TeslemetrySensorEntityDescription(
        key="di_motor_current_rear_right",
        streaming_key=Signal.DI_MOTOR_CURRENT_RER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
    ),
    TeslemetrySensorEntityDescription(
        key="di_salve_torque_command",
        streaming_key=Signal.DI_SLAVE_TORQUE_CMD,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_state_front",
        streaming_key=Signal.DI_STATE_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_state_rear",
        streaming_key=Signal.DI_STATE_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_state_rear_left",
        streaming_key=Signal.DI_STATE_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_state_rear_right",
        streaming_key=Signal.DI_STATE_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_stator_temp_front",
        streaming_key=Signal.DI_STATOR_TEMP_F,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_stator_temp_rear",
        streaming_key=Signal.DI_STATOR_TEMP_R,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_stator_temp_rear_left",
        streaming_key=Signal.DI_STATOR_TEMP_REL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_stator_temp_rear_right",
        streaming_key=Signal.DI_STATOR_TEMP_RER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_actual_front",
        streaming_key=Signal.DI_TORQUE_ACTUAL_F,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_actual_rear",
        streaming_key=Signal.DI_TORQUE_ACTUAL_R,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_actual_rear_left",
        streaming_key=Signal.DI_TORQUE_ACTUAL_REL,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_actual_rear_right",
        streaming_key=Signal.DI_TORQUE_ACTUAL_RER,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_torque_motor",
        streaming_key=Signal.DI_TORQUEMOTOR,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_voltage_battery_front",
        streaming_key=Signal.DI_V_BAT_F,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_voltage_battery_rear",
        streaming_key=Signal.DI_V_BAT_R,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_voltage_battery_rear_left",
        streaming_key=Signal.DI_V_BAT_REL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="di_voltage_battery_rear_right",
        streaming_key=Signal.DI_V_BAT_RER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="energy_remaining",
        streaming_key=Signal.ENERGY_REMAINING,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="forward_collision_warning",
        streaming_key=Signal.FORWARD_COLLISION_WARNING,
        entity_registry_enabled_default=False,
        streaming_value_fn=ForwardCollisionSensitivity.get,
        options=ForwardCollisionSensitivity.options,
        device_class=SensorDeviceClass.ENUM,

    ),
    TeslemetrySensorEntityDescription(
        key="gps_heading",
        streaming_key=Signal.GPS_HEADING,
        native_unit_of_measurement=DEGREE,
        entity_registry_enabled_default=False,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="guest_mode_mobile_access_state",
        streaming_key=Signal.GUEST_MODE_MOBILE_ACCESS_STATE,
        entity_registry_enabled_default=False,
        streaming_value_fn=GuestModeMobileAccess.get,
        options=GuestModeMobileAccess.options,
        device_class=SensorDeviceClass.ENUM,
    ),
    TeslemetrySensorEntityDescription(
        key="hvil",
        streaming_key=Signal.HVIL,
        entity_registry_enabled_default=False,
        streaming_value_fn=HvilStatus.get,
        options=HvilStatus.options,
        device_class=SensorDeviceClass.ENUM,
    ),
    TeslemetrySensorEntityDescription(
        key="isolation_resistance",
        streaming_key=Signal.ISOLATION_RESISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="lane_departure_avoidance",
        streaming_key=Signal.LANE_DEPARTURE_AVOIDANCE,
        entity_registry_enabled_default=False,
        streaming_value_fn=LaneAssistLevel.get,
        options=LaneAssistLevel.options,
        device_class=SensorDeviceClass.ENUM,
    ),
    TeslemetrySensorEntityDescription(
        key="lateral_acceleration",
        streaming_key=Signal.LATERAL_ACCELERATION,
        entity_registry_enabled_default=False,
        suggested_display_precision=3,
    ),
    TeslemetrySensorEntityDescription(
        key="lifetime_energy_gained_regen",
        streaming_key=Signal.LIFETIME_ENERGY_GAINED_REGEN,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="lifetime_energy_used",
        streaming_key=Signal.LIFETIME_ENERGY_USED,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="lifetime_energy_used_drive",
        streaming_key=Signal.LIFETIME_ENERGY_USED_DRIVE,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="longitudinal_acceleration",
        streaming_key=Signal.LONGITUDINAL_ACCELERATION,
        entity_registry_enabled_default=False,
        suggested_display_precision=3,
    ),
    TeslemetrySensorEntityDescription(
        key="module_temp_max",
        streaming_key=Signal.MODULE_TEMP_MAX,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
    ),
    TeslemetrySensorEntityDescription(
        key="module_temp_min",
        streaming_key=Signal.MODULE_TEMP_MIN,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        suggested_display_precision=0
    ),
    TeslemetrySensorEntityDescription(
        key="no_enough_power_to_heat",
        streaming_key=Signal.NOT_ENOUGH_POWER_TO_HEAT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="brick_number_voltage_max",
        streaming_key=Signal.NUM_BRICK_VOLTAGE_MAX,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="brick_number_voltage_min",
        streaming_key=Signal.NUM_BRICK_VOLTAGE_MIN,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="module_number_temp_max",
        streaming_key=Signal.NUM_MODULE_TEMP_MAX,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="module_number_temp_min",
        streaming_key=Signal.NUM_MODULE_TEMP_MIN,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="pack_current",
        streaming_key=Signal.PACK_CURRENT,
        suggested_display_precision=1,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="pack_voltage",
        suggested_display_precision=2,
        streaming_key=Signal.PACK_VOLTAGE,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="paired_key_quantity",
        streaming_key=Signal.PAIRED_PHONE_KEY_AND_KEY_FOB_QTY,
        entity_registry_enabled_default=False,
        #streaming_value_fn=lambda x: int(x),
    ),
    TeslemetrySensorEntityDescription(
        key="pedal_position",
        streaming_key=Signal.PEDAL_POSITION,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="rated_range",
        streaming_key=Signal.RATED_RANGE,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="sentry_mode",
        streaming_key=Signal.SENTRY_MODE,
        streaming_value_fn=SentryModeState.get,
        options=SentryModeState.options,
        device_class=SensorDeviceClass.ENUM,
    ),
    TeslemetrySensorEntityDescription(
        key="state_of_charge",
        streaming_key=Signal.SOC,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="speed_limit_warning",
        streaming_key=Signal.SPEED_LIMIT_WARNING,
        entity_registry_enabled_default=False,
        streaming_value_fn=SpeedAssistLevel.get,
        options=SpeedAssistLevel.options,
        device_class=SensorDeviceClass.ENUM,
    ),
    TeslemetrySensorEntityDescription(
        key="trim",
        streaming_key=Signal.TRIM,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="vehicle_name",
        streaming_key=Signal.VEHICLE_NAME,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="center_display",
        streaming_key=Signal.CENTER_DISPLAY,
        streaming_firmware="2024.44.25",
        streaming_value_fn=DisplayState.get,
        options=DisplayState.options,
        device_class=SensorDeviceClass.ENUM,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="efficiency_package",
        streaming_key=Signal.EFFICIENCY_PACKAGE,
        streaming_firmware="2024.44.25",
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="estimated_hours_to_charge_termination",
        streaming_key=Signal.ESTIMATED_HOURS_TO_CHARGE_TERMINATION,
        streaming_firmware="2024.44.25",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="drive_state_expected_energy_percent_at_trip_arrival",
        streaming_key=Signal.EXPECTED_ENERGY_PERCENT_AT_TRIP_ARRIVAL,
        streaming_firmware="2024.44.25",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=1,
    ),
    TeslemetrySensorEntityDescription(
        key="homelink_device_count",
        streaming_key=Signal.HOMELINK_DEVICE_COUNT,
        streaming_firmware="2024.44.25",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="powershare_hours_left",
        streaming_key=Signal.POWERSHARE_HOURS_LEFT,
        streaming_firmware="2024.44.25",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="powershare_instantaneous_power_kw",
        streaming_key=Signal.POWERSHARE_INSTANTANEOUS_POWER_KW,
        streaming_firmware="2024.44.25",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="powershare_status",
        streaming_key=Signal.POWERSHARE_STATUS,
        streaming_firmware="2024.44.25",
        entity_category=EntityCategory.DIAGNOSTIC,
        streaming_value_fn=PowershareState.get,
        options=PowershareState.options,
        device_class=SensorDeviceClass.ENUM,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="powershare_stop_reason",
        streaming_key=Signal.POWERSHARE_STOP_REASON,
        streaming_firmware="2024.44.25",
        entity_category=EntityCategory.DIAGNOSTIC,
        streaming_value_fn=PowershareStopReasonStatus.get,
        options=PowershareStopReasonStatus.options,
        device_class=SensorDeviceClass.ENUM,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="powershare_type",
        streaming_key=Signal.POWERSHARE_TYPE,
        streaming_firmware="2024.44.25",
        entity_category=EntityCategory.DIAGNOSTIC,
        streaming_value_fn=PowershareTypeStatus.get,
        options=PowershareTypeStatus.options,
        entity_registry_enabled_default=False,
    ),
    TeslemetrySensorEntityDescription(
        key="tpms_hard_warnings",
        streaming_key=Signal.TPMS_HARD_WARNINGS,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="tpms_soft_warnings",
        streaming_key=Signal.TPMS_SOFT_WARNINGS,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetrySensorEntityDescription(
        key="wheel_type",
        streaming_key=Signal.WHEEL_TYPE,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)
@dataclass(frozen=True, kw_only=True)
class TeslemetryTimeEntityDescription(SensorEntityDescription):
    """Describes Teslemetry Sensor entity."""

    polling: bool = False
    variance: int = 60
    streaming_key: Signal | None = None
    streaming_firmware: str = "2024.26"
    value_fn: Callable[[int|float|dict], timedelta]
    available_fn: Callable[[Any], bool] = lambda x: True


VEHICLE_TIME_DESCRIPTIONS: tuple[TeslemetryTimeEntityDescription, ...] = (
    TeslemetryTimeEntityDescription(
        key="charge_state_time_to_full_charge",
        polling=True,
        value_fn=lambda x: timedelta(hours=x),
        available_fn=lambda x: isinstance(x, (int | float)) and x > 0,
        streaming_key=Signal.TIME_TO_FULL_CHARGE,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryTimeEntityDescription(
        key="drive_state_active_route_minutes_to_arrival",
        polling=True,
        value_fn=lambda x: timedelta(minutes=x),
        available_fn=lambda x: isinstance(x, (int | float)) and x > 0,
        streaming_key=Signal.MINUTES_TO_ARRIVAL,
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    TeslemetryTimeEntityDescription(
        key="route_last_updated",
        value_fn=lambda x: timedelta(hours=x['hour'], minutes=x['minute'], seconds=x['second']),
        available_fn=lambda x: isinstance(x, dict),
        streaming_key=Signal.ROUTE_LAST_UPDATED,
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
        ],
    ),
)

WALL_CONNECTOR_DESCRIPTIONS: tuple[
    TeslemetryEnergySensorEntityDescription, ...
] = (
    TeslemetryEnergySensorEntityDescription(
        key="wall_connector_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        options=list(WALL_CONNECTOR_STATES.values()),
        device_class=SensorDeviceClass.ENUM,
        value_fn=lambda value: WALL_CONNECTOR_STATES.get(cast(str, value)),
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
    hass: HomeAssistant, entry: TeslemetryConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry sensor platform from a config entry."""

    entities = []
    for vehicle in entry.runtime_data.vehicles:
        if not vehicle.api.pre2021:
            entities.extend((
                TeslemetryVehicleEventSensorEntity(vehicle, "alerts"),
                TeslemetryVehicleEventSensorEntity(vehicle, "errors")
            ))
        for description in VEHICLE_DESCRIPTIONS:
            if not vehicle.api.pre2021 and description.streaming_key and vehicle.firmware >= description.streaming_firmware:
                entities.append(TeslemetryVehicleStreamSensorEntity(vehicle, description))
            elif description.polling:
                entities.append(TeslemetryVehiclePollingSensorEntity(vehicle, description))
        for description in VEHICLE_TIME_DESCRIPTIONS:
            if not vehicle.api.pre2021 and vehicle.firmware >= description.streaming_firmware:
                entities.append(TeslemetryVehicleTimeStreamSensorEntity(vehicle, description))
            elif description.polling:
                entities.append(TeslemetryVehicleTimeSensorEntity(vehicle, description))

    for energysite in entry.runtime_data.energysites:
        for description in ENERGY_LIVE_DESCRIPTIONS:
            if description.key in energysite.live_coordinator.data or description.key == "percentage_charged":
                entities.append(TeslemetryEnergyLiveSensorEntity(energysite, description))
        for din in energysite.live_coordinator.data.get("wall_connectors", {}):
            for description in WALL_CONNECTOR_DESCRIPTIONS:
                entities.append(TeslemetryWallConnectorSensorEntity(energysite, din, description))
            entities.append(TeslemetryWallConnectorVehicleSensorEntity(energysite, din, entry.runtime_data.vehicles))
        for description in ENERGY_INFO_DESCRIPTIONS:
            if description.key in energysite.info_coordinator.data:
                entities.append(TeslemetryEnergyInfoSensorEntity(energysite, description))
        if energysite.history_coordinator is not None:
            for description in ENERGY_HISTORY_DESCRIPTIONS:
                entities.append(TeslemetryEnergyHistorySensorEntity(energysite, description))

    entities.append(TeslemetryCreditBalanceSensor(entry.unique_id, entry.runtime_data))

    async_add_entities(entities)


class TeslemetryVehiclePollingSensorEntity(TeslemetryVehicleEntity, SensorEntity):
    """Base class for Teslemetry vehicle metric sensors."""

    entity_description: TeslemetrySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetrySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""

        if self.entity_description.available_fn(self._value):
            self._attr_available = True
            self._attr_native_value = self.entity_description.polling_value_fn(self._value)
        else:
            self._attr_available = False
            self._attr_native_value = None

class TeslemetryVehicleStreamSensorEntity(TeslemetryVehicleStreamSingleEntity, RestoreSensor):
    """Base class for Teslemetry vehicle streaming sensors."""

    entity_description: TeslemetrySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetrySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        assert description.streaming_key
        super().__init__(data, description.key, description.streaming_key)

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        if (sensor_data := await self.async_get_last_sensor_data()) is not None:
            if sensor_data.native_value is not None:
                # This should be temporary
                if isinstance(sensor_data.native_value, str):
                    sensor_data.native_value = self.entity_description.streaming_value_fn(sensor_data.native_value)
                self._attr_native_value = sensor_data.native_value

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        if self.entity_description.available_fn(value):
            self._attr_available = True
            self._attr_native_value = self.entity_description.streaming_value_fn(value)
        else:
            self._attr_available = False
            self._attr_native_value = None

        if self._attr_native_value == "Unknown":
            self._attr_native_value = None

class TeslemetryVehicleEventSensorEntity(RestoreSensor):
    """Base class for Teslemetry vehicle event sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        data: TeslemetryVehicleData,
        type: str
    ) -> None:
        """Initialize the sensor."""
        self.type = type
        self.stream = data.stream
        self.vin = data.vin
        self._attr_translation_key = type
        self._attr_unique_id = f"{data.vin}-{type}"
        self._attr_device_info = data.device
        self._last = "0"
        self.timestamp = "createdAt" if type == "errors" else "startedAt"

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.stream.async_add_listener(
                self._handle_stream_update,
                {"vin": self.vin, self.type: None},
            )
        )

        if (sensor_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = sensor_data.native_value

    def _handle_stream_update(self, data) -> None:
        """Update the value of the entity."""
        for event in data[self.type]:
            if event[self.timestamp] > self._last:
                self._last = event[self.timestamp]
                self._attr_native_value = event["name"]
                self._attributes = event.get("tags", None)
                self.async_write_ha_state()


class TeslemetryVehicleTimeSensorEntity(TeslemetryVehicleEntity, SensorEntity):
    """Base class for Teslemetry vehicle metric sensors."""

    entity_description: TeslemetryTimeEntityDescription
    _last_value: float | None = None

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetryTimeEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._time_value = ignore_variance(
            func=lambda value: dt_util.utcnow() + value,
            ignored_variance=timedelta(minutes=1),
        )

        super().__init__(data, description.key)
        self._attr_translation_key = f"{self.entity_description.key}_timestamp"
        self._attr_unique_id = f"{data.vin}-{description.key}_timestamp"

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""

        value = self._value
        self._attr_available = self.entity_description.available_fn(value)
        if(self._attr_available):
            delta = self.entity_description.value_fn(value)
            if delta.total_seconds() == self._last_value:
                return
            self._last_value = delta.total_seconds()
            self._attr_native_value = self._time_value(delta)


class TeslemetryVehicleTimeStreamSensorEntity(TeslemetryVehicleStreamSingleEntity, SensorEntity):
    """Base class for Teslemetry vehicle metric sensors."""

    entity_description: TeslemetryTimeEntityDescription
    _last_value: float | None = None

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetryTimeEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._time_value = ignore_variance(
            func=lambda value: dt_util.utcnow() + value,
            ignored_variance=timedelta(minutes=1),
        )
        assert description.streaming_key
        super().__init__(data, description.key, description.streaming_key)
        self._attr_translation_key = f"{self.entity_description.key}_timestamp"
        self._attr_unique_id = f"{data.vin}-{description.key}_timestamp"

    def _async_value_from_stream(self, value) -> None:
        """Update the attributes of the sensor."""

        self._attr_available = self.entity_description.available_fn(value)
        if(self._attr_available):
            delta = self.entity_description.value_fn(value)
            if delta.total_seconds() == self._last_value:
                return
            self._last_value = delta.total_seconds()
            self._attr_native_value = self._time_value(delta)


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

class TeslemetryCreditBalanceSensor(RestoreSensor):
    """Entity for Teslemetry Credit balance."""

    _attr_has_entity_name = True
    stream: TeslemetryStream
    _attr_state_class=SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision=0

    def __init__(
        self, uid: str, data: TeslemetryData
    ) -> None:
        """Initialize common aspects of a Teslemetry entity."""

        self._attr_translation_key = "credit_balance"
        self._attr_unique_id = f"{uid}_credit_balance"
        self.stream = data.stream

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        if (sensor_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = sensor_data.native_value

        self.async_on_remove(
            self.stream.listen_Balance(self._async_update)
        )

    def _async_update(self, value: int) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = value
        self.async_write_ha_state()
