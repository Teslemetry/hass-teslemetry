"""Constants used by Teslemetry integration."""
from __future__ import annotations

from enum import StrEnum, IntEnum
import logging

DOMAIN = "teslemetry"

LOGGER = logging.getLogger(__package__)

MODELS = {
    "S": "Model S",
    "3": "Model 3",
    "X": "Model X",
    "Y": "Model Y",
}


class TeslemetryState(StrEnum):
    """Teslemetry Vehicle States."""

    ONLINE = "online"
    ASLEEP = "asleep"
    OFFLINE = "offline"


class TeslemetryClimateSide(StrEnum):
    """Teslemetry Climate Keeper Modes."""

    DRIVER = "driver_temp"
    PASSENGER = "passenger_temp"


class TeslemetrySeatHeaterOptions(StrEnum):
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
