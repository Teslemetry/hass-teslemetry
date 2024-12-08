"""Binary Sensor descriptions for Teslemetry integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from teslemetry_stream import TelemetryFields

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.typing import StateType

from .const import TeslemetryPollingKeys


@dataclass(frozen=True, kw_only=True)
class TeslemetryBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes Teslemetry binary sensor entity."""

    polling_value_fn: Callable[[StateType], bool] = lambda x: bool(x)
    polling_parent: TeslemetryPollingKeys | None = None
    streaming_key: TelemetryFields | None = None
    streaming_firmware: str = "2024.26"
    streaming_value_fn: Callable[[StateType], bool] = lambda x: bool(x)


VEHICLE_DESCRIPTIONS: tuple[TeslemetryBinarySensorEntityDescription, ...] = (
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_battery_heater_on",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.BATTERY_HEATER_ON,

        device_class=BinarySensorDeviceClass.HEAT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_charger_phases",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.CHARGER_PHASES,
        polling_value_fn=lambda x: int(x) > 1,
        streaming_value_fn=lambda x: int(x) > 1,

        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_preconditioning_enabled",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.PRECONDITIONING_ENABLED,

        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="climate_state_is_preconditioning",
        polling_parent=TeslemetryPollingKeys.CLIMATE_STATE,

        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_scheduled_charging_pending",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        streaming_key=TelemetryFields.SCHEDULED_CHARGING_PENDING,

        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_trip_charging",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,

        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_state_conn_charge_cable",
        polling_parent=TeslemetryPollingKeys.CHARGE_STATE,
        polling_value_fn=lambda x: x != "<invalid>",

        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="climate_state_cabin_overheat_protection_actively_cooling",
        polling_parent=TeslemetryPollingKeys.CLIMATE_STATE,

        device_class=BinarySensorDeviceClass.HEAT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_dashcam_state",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,

        device_class=BinarySensorDeviceClass.RUNNING,
        polling_value_fn=lambda x: x == "Recording",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_is_user_present",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,

        device_class=BinarySensorDeviceClass.PRESENCE,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_tpms_soft_warning_fl",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,

        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_tpms_soft_warning_fr",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,

        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_tpms_soft_warning_rl",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,

        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_tpms_soft_warning_rr",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,

        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_fd_window",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,
        streaming_key=TelemetryFields.FD_WINDOW,

        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_fp_window",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,
        streaming_key=TelemetryFields.FP_WINDOW,

        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_rd_window",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,
        streaming_key=TelemetryFields.RD_WINDOW,

        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_rp_window",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,
        streaming_key=TelemetryFields.RP_WINDOW,

        device_class=BinarySensorDeviceClass.WINDOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_df",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,

        device_class=BinarySensorDeviceClass.DOOR,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_dr",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,

        device_class=BinarySensorDeviceClass.DOOR,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_pf",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,

        device_class=BinarySensorDeviceClass.DOOR,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="vehicle_state_pr",
        polling_parent=TeslemetryPollingKeys.VEHICLE_STATE,

        device_class=BinarySensorDeviceClass.DOOR,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="automatic_blind_spot_camera",
        streaming_key=TelemetryFields.AUTOMATIC_BLIND_SPOT_CAMERA,

        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="automatic_emergency_braking_off",
        streaming_key=TelemetryFields.AUTOMATIC_EMERGENCY_BRAKING_OFF,

        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="blind_spot_collision_warning_chime",
        streaming_key=TelemetryFields.BLIND_SPOT_COLLISION_WARNING_CHIME,

        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="bms_full_charge_complete",
        streaming_key=TelemetryFields.BMS_FULL_CHARGE_COMPLETE,

        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="brake_pedal",
        streaming_key=TelemetryFields.BRAKE_PEDAL,

        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_enable_request",
        streaming_key=TelemetryFields.CHARGE_ENABLE_REQUEST,

        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="charge_port_cold_weather_mode",
        streaming_key=TelemetryFields.CHARGE_PORT_COLD_WEATHER_MODE,

        entity_registry_enabled_default=False,
    ),
    TeslemetryBinarySensorEntityDescription(
        key="service_mode",
        streaming_key=TelemetryFields.SERVICE_MODE,

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
