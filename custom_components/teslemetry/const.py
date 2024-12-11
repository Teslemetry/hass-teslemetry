"""Constants used by Teslemetry integration."""

from __future__ import annotations

from enum import StrEnum, IntEnum
import logging

DOMAIN = "teslemetry"

STREAMING_GAP = 60000

LOGGER = logging.getLogger(__package__)

MODELS = {
    "S": "Model S",
    "3": "Model 3",
    "X": "Model X",
    "Y": "Model Y",
}

ENERGY_HISTORY_FIELDS = [
    "solar_energy_exported",
    "generator_energy_exported",
    "grid_energy_imported",
    "grid_services_energy_imported",
    "grid_services_energy_exported",
    "grid_energy_exported_from_solar",
    "grid_energy_exported_from_generator",
    "grid_energy_exported_from_battery",
    "battery_energy_exported",
    "battery_energy_imported_from_grid",
    "battery_energy_imported_from_solar",
    "battery_energy_imported_from_generator",
    "consumer_energy_imported_from_grid",
    "consumer_energy_imported_from_solar",
    "consumer_energy_imported_from_battery",
    "consumer_energy_imported_from_generator",
    "total_home_usage",
    "total_battery_charge",
    "total_battery_discharge",
    "total_solar_generation",
    "total_grid_energy_exported",
]

class TeslemetryUpdateType(StrEnum):
    """Teslemetry Update Types."""

    NONE = "none"
    POLLING = "polling"
    STREAMING = "streaming"


class TeslemetryPollingKeys(StrEnum):
    """Teslemetry Timestamps."""

    VEHICLE_STATE = "vehicle_state"
    DRIVE_STATE = "drive_state"
    CHARGE_STATE = "charge_state"
    CLIMATE_STATE = "climate_state"
    GUI_SETTINGS = "gui_settings"
    VEHICLE_CONFIG = "vehicle_config"

class TeslemetryTimestamp(StrEnum):
    """Teslemetry Timestamps."""

    VEHICLE_STATE = "vehicle_state_timestamp"
    DRIVE_STATE = "drive_state_timestamp"
    CHARGE_STATE = "charge_state_timestamp"
    CLIMATE_STATE = "climate_state_timestamp"
    GUI_SETTINGS = "gui_settings_timestamp"
    VEHICLE_CONFIG = "vehicle_config_timestamp"


class TeslemetryState(StrEnum):
    """Teslemetry Vehicle States."""

    ONLINE = "online"
    ASLEEP = "asleep"
    OFFLINE = "offline"


class TeslemetryClimateSide(StrEnum):
    """Teslemetry Climate Keeper Modes."""

    DRIVER = "driver_temp"
    PASSENGER = "passenger_temp"


class TeslemetryHeaterOptions(StrEnum):
    """Teslemetry seat heater options."""

    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TeslemetryClimateKeeper(StrEnum):
    """Teslemetry Climate Keeper Modes."""

    OFF = "off"
    ON = "on"
    DOG = "dog"
    CAMP = "camp"


class TeslemetryUpdateStatus(StrEnum):
    """Teslemetry Update Statuses."""

    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    WIFI_WAIT = "downloading_wifi_wait"
    SCHEDULED = "scheduled"


class TeslemetryCoverStates(IntEnum):
    """Teslemetry Cover states."""

    CLOSED = 0
    OPEN = 1


class TeslemetryChargeCableLockStates(StrEnum):
    """Teslemetry Charge Cable Lock states."""

    ENGAGED = "Engaged"
    DISENGAGED = "Disengaged"
