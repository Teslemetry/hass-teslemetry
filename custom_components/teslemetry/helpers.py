"""Teslemetry helper functions."""

import asyncio
from typing import Any
from teslemetry_stream import TeslemetryStream
from tesla_fleet_api.const import TelemetryField
from tesla_fleet_api.exceptions import TeslaFleetError

from homeassistant.exceptions import HomeAssistantError
from .const import DOMAIN, LOGGER, TeslemetryState


def flatten(data: dict[str, Any], parent: str | None = None) -> dict[str, Any]:
    """Flatten the data structure."""
    result = {}
    for key, value in data.items():
        if parent:
            key = f"{parent}_{key}"
        if isinstance(value, dict):
            result.update(flatten(value, key))
        else:
            result[key] = value
    return result


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
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="wake_up_failed",
                    translation_placeholders={"message": e.message},
                ) from e
            vehicle.coordinator.data["state"] = state
            if state != TeslemetryState.ONLINE:
                times += 1
                if times >= 4:  # Give up after 30 seconds total
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="wake_up_timeout",
                    )
                await asyncio.sleep(times * 5)


async def handle_command(command) -> dict[str, Any]:
    """Handle a command."""
    try:
        result = await command
    except TeslaFleetError as e:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_exception",
            translation_placeholders={"message": e.message},
        ) from e
    LOGGER.debug("Command result: %s", result)
    return result


async def handle_vehicle_command(command) -> dict[str, Any]:
    """Handle a vehicle command."""
    result = await handle_command(command)
    if (response := result.get("response")) is None:
        if error := result.get("error"):
            # No response with error
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_error",
                translation_placeholders={"error": error},
            )
        # No response without error (unexpected)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_no_response",
        )
    if (result := response.get("result")) is not True:
        if reason := response.get("reason"):
            if reason in ("already_set", "not_charging", "requested"):
                # Reason is acceptable
                return result
            # Result of false with reason
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_reason",
                translation_placeholders={"reason": reason},
            )
        # Result of false without reason (unexpected)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_no_result"
        )
    # Response with result of true
    return result


def auto_type(value) -> int | float | bool | str:
    """Automatically cast a string to a type."""

    if not isinstance(value, str):
        return value

    if value.isdigit():
        return int(value)
    try:
        return float(value)
    except ValueError:
        pass

    if value.lower() in ["true", "false"]:
        return value.lower() == "true"

    return value


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

class AddStreamFields:
    """Handle streaming field updates."""

    def __init__(self, stream: TeslemetryStream, vin: str):
        # A dictionary of TelemetryField keys and null values
        self.stream: TeslemetryStream = stream
        self.vin: str = vin
        self.fields: dict[TelemetryField, None] = {}
        self.lock = asyncio.Lock()

    async def add(self, field: TelemetryField) -> None:
        """Handle vehicle data from the stream."""
        if field in self.stream.fields:
            LOGGER.debug("Streaming field %s already enabled @ %ss", field, self.stream.fields[field].get('interval_seconds'))
            return
        self.fields[field] = None
        async with self.lock:
            # Short circuit if no fields are present
            if len(self.fields) == 0:
                return
            # Collect additional fields before sending
            await asyncio.sleep(1)
            # Copy the field list and empty it
            fields = self.fields.copy()
            self.fields.clear()

            resp = await self.stream.update_fields(fields, self.vin)
            if(resp.get("response",{}).get("updated_vehicles") == 1):
                LOGGER.debug("Added streaming fields %s", ", ".join(fields.keys()))
            else:
                LOGGER.warning("Unable to add streaming fields %s", ", ".join(fields.keys()))
