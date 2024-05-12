"""Teslemetry helper functions."""

import asyncio
from typing import Any
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from tesla_fleet_api.exceptions import TeslaFleetError
from .const import LOGGER, TeslemetryState


async def wake_up_vehicle(vehicle):
    """Wake up a vehicle."""
    async with vehicle.wakelock:
        times = 0
        while vehicle.coordinator.data["state"] != TeslemetryState.ONLINE:
            try:
                if times == 0:
                    cmd = await vehicle.api.wake_up()
                else:
                    cmd = await vehicle.api.vehicle()
                state = cmd["response"]["state"]
            except TeslaFleetError as e:
                raise HomeAssistantError(str(e)) from e
            except TypeError as e:
                raise HomeAssistantError("Invalid response from Teslemetry") from e
            vehicle.coordinator.data["state"] = state
            if state != TeslemetryState.ONLINE:
                times += 1
                if times >= 4:  # Give up after 30 seconds total
                    raise HomeAssistantError("Could not wake up vehicle")
                await asyncio.sleep(times * 5)


async def handle_command(command) -> dict[str, Any]:
    """Handle a command."""
    try:
        result = await command
        LOGGER.debug("Command result: %s", result)
    except TeslaFleetError as e:
        LOGGER.info("Command error: %s", e.message)
        raise HomeAssistantError(f"Teslemetry command failed, {e.message}") from e
    return result

async def handle_vehicle_command(command) -> dict[str, Any]:
    """Handle a vehicle command response"""
    result = await handle_command(command)
    if (response := result.get("response")) is None:
        if message := result.get("error"):
            # No response with error
            LOGGER.info("Command error: %s", message)
            raise HomeAssistantError(message)
        # No response without error (unexpected)
        LOGGER.error("Unknown response: %s", response)
        raise HomeAssistantError("Unknown response")
    if (response.get("result")) is not True:
        if message := response.get("reason"):
            if message in ("already_set","not_charging","requested"):
                return result
            # Result of false with reason
            LOGGER.info("Command failure: %s", message)
            raise HomeAssistantError(message)
        # Result of false without reason (unexpected)
        LOGGER.error("Unknown response: %s", response)
        raise HomeAssistantError("Unknown response")
    # Response with result of true
    return result


def auto_type(str):
    """Automatically cast a string to a type."""
    if str.isdigit():
        return int(str)
    try:
        return float(str)
    except ValueError:
        pass

    if str.lower() in ["true", "false"]:
        return str.lower() == "true"

    return str


def ignore_drop(change: int | float = 1):
    """Ignore a drop in value."""
    _last_value = None

    def _ignore_drop(value):
        try:
            value = float(value)
        except ValueError:
            return None

        nonlocal _last_value, change
        if _last_value is None or value > _last_value or (_last_value - value) > change:
            _last_value = value
        return _last_value

    return _ignore_drop
