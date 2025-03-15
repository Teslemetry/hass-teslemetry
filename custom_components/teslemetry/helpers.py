"""Teslemetry helper functions."""

import time
import json
from typing import Any
from tesla_fleet_api.exceptions import TeslaFleetError

from homeassistant.exceptions import HomeAssistantError
from .const import DOMAIN, LOGGER


def flatten(data: dict[str, Any], parent: str | None = None, exceptions: list[str]=[]) -> dict[str, Any]:
    """Flatten the data structure."""
    result = {}
    for key, value in data.items():
        exception = key in exceptions
        if parent:
            key = f"{parent}_{key}"
        if isinstance(value, dict) and not exception:
            result.update(flatten(value, key, exceptions))
        else:
            result[key] = value
    return result


async def handle_command(command) -> dict[str, Any]:
    """Handle a command."""
    start_time = time.time()
    try:
        res = await command
    except TeslaFleetError as e:
        elapsed_time = time.time() - start_time
        LOGGER.warning("Command execution took %.2f seconds and failed with %s", elapsed_time, e)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_exception",
            translation_placeholders={"message": e.message},
        ) from e

    elapsed_time = time.time() - start_time
    LOGGER.info("Command execution took %.2f seconds and returned %s", elapsed_time, json.dumps(res))
    return res


async def handle_vehicle_command(command) -> bool:
    """Handle a vehicle command."""

    res = await handle_command(command)
    if (response := res.get("response")) is None:
        if error := res.get("error"):
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
    if (response.get("result")) is not True:
        if reason := response.get("reason"):
            if reason in ("already_set", "not_charging", "requested"):
                # Reason is acceptable
                return False
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
    return True


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
