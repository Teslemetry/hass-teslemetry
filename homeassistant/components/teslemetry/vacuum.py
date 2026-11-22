"""Vacuum platform for the Teslemetry Roadster Labs easter egg.

Entirely local and optimistic: nothing here talks to a real vehicle.
"""

from typing import Any, override

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TeslemetryConfigEntry
from .const import DOMAIN
from .models import TeslemetryRoadsterData

PARALLEL_UPDATES = 0

FAN_SPEEDS = ["gentle_breeze", "standard", "ludicrous", "upside_down"]
COMMAND_LAND = "land"
# Battery cost of each cold-air thruster trick
TRICKS = {"fly": 10, "hover": 5, "barrel_roll": 15}
START_COST = 5
CLEAN_SPOT_COST = 2


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Roadster vacuum when its Labs preview feature is enabled."""
    if (roadster := entry.runtime_data.roadster) is not None:
        async_add_entities([TeslemetryRoadsterVacuumEntity(roadster, entry.entry_id)])


class TeslemetryRoadsterVacuumEntity(StateVacuumEntity):
    """A Tesla Roadster that cleans with its fan suction and cold-air thrusters."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_translation_key = "roadster"
    _attr_activity = VacuumActivity.DOCKED
    _attr_fan_speed = "standard"
    _attr_fan_speed_list = FAN_SPEEDS
    _attr_supported_features = (
        VacuumEntityFeature.STATE
        | VacuumEntityFeature.START
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.LOCATE
        | VacuumEntityFeature.CLEAN_SPOT
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.SEND_COMMAND
    )

    def __init__(self, roadster: TeslemetryRoadsterData, entry_id: str) -> None:
        """Initialize the Roadster vacuum."""
        self.roadster = roadster
        self._attr_unique_id = f"{entry_id}_roadster"
        self._attr_device_info = roadster.device

    def _async_drive(self, activity: VacuumActivity, battery_cost: int = 0) -> None:
        """Set the activity, spending battery on it."""
        if battery_cost > self.roadster.battery_level:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="roadster_low_battery"
            )
        self._attr_activity = activity
        self.roadster.async_set_battery_level(
            self.roadster.battery_level - battery_cost
        )
        self.async_write_ha_state()

    @override
    async def async_start(self) -> None:
        """Start cleaning."""
        self._async_drive(VacuumActivity.CLEANING, START_COST)

    @override
    async def async_pause(self) -> None:
        """Pause cleaning."""
        self._async_drive(VacuumActivity.PAUSED)

    @override
    async def async_stop(self, **kwargs: Any) -> None:
        """Stop cleaning."""
        self._async_drive(VacuumActivity.IDLE)

    @override
    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Return to the Supercharger, which charges instantly."""
        self.roadster.async_set_battery_level(100)
        self._async_drive(VacuumActivity.DOCKED)

    @override
    async def async_clean_spot(self, **kwargs: Any) -> None:
        """Clean a spot."""
        self._async_drive(VacuumActivity.CLEANING, CLEAN_SPOT_COST)

    @override
    async def async_locate(self, **kwargs: Any) -> None:
        """Locate the Roadster, which is right where you left it."""

    @override
    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set the fan speed."""
        if fan_speed not in FAN_SPEEDS:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="roadster_invalid_fan_speed",
                translation_placeholders={
                    "fan_speed": fan_speed,
                    "fan_speeds": ", ".join(FAN_SPEEDS),
                },
            )
        self._attr_fan_speed = fan_speed
        self.async_write_ha_state()

    @override
    async def async_send_command(
        self,
        command: str,
        params: dict[str, Any] | list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Perform a cold-air thruster trick, or land."""
        if command == COMMAND_LAND:
            self._async_drive(VacuumActivity.IDLE)
            return
        if command not in TRICKS:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="roadster_unknown_trick",
                translation_placeholders={
                    "command": command,
                    "commands": ", ".join([*TRICKS, COMMAND_LAND]),
                },
            )
        self._async_drive(VacuumActivity.CLEANING, TRICKS[command])
