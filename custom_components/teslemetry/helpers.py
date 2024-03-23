"""Teslemetry helper functions."""

import asyncio
from homeassistant.exceptions import HomeAssistantError
from tesla_fleet_api.exceptions import TeslaFleetError
from .const import TeslemetryState


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
