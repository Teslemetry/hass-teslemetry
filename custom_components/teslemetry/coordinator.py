"""Teslemetry Data Coordinator."""
from datetime import timedelta
from typing import Any

from tesla_fleet_api import EnergySpecific, VehicleSpecific
from tesla_fleet_api.const import VehicleDataEndpoints
from tesla_fleet_api.exceptions import TeslaFleetError, VehicleOffline

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import LOGGER, TeslemetryState

VEHICLE_INTERVAL = timedelta(seconds=30)
ENERGY_LIVE_INTERVAL = timedelta(seconds=30)
ENERGY_INFO_INTERVAL = timedelta(seconds=300)


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


class TeslemetryVehicleDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching data from the Teslemetry API."""

    def __init__(
        self, hass: HomeAssistant, api: VehicleSpecific, product: dict
    ) -> None:
        """Initialize Teslemetry Vehicle Update Coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name="Teslemetry Vehicle",
            update_interval=VEHICLE_INTERVAL,
        )
        self.api = api
        self.data = product

    async def _async_update_data(self) -> dict[str, Any]:
        """Update vehicle data using Teslemetry API."""
        try:
            data = await self.api.vehicle_data(
                #endpoints=[
                    #VehicleDataEndpoints.CHARGE_STATE,
                    #VehicleDataEndpoints.CLIMATE_STATE,
                    #VehicleDataEndpoints.CLOSURES_STATE,
                    #VehicleDataEndpoints.DRIVE_STATE,
                    #VehicleDataEndpoints.GUI_SETTINGS,
                    #VehicleDataEndpoints.LOCATION_DATA,
                    #VehicleDataEndpoints.VEHICLE_CONFIG,
                    #VehicleDataEndpoints.VEHICLE_STATE,
                #]
            )
        except VehicleOffline:
            self.data["state"] = TeslemetryState.OFFLINE
            return self.data
        except TeslaFleetError as e:
            raise UpdateFailed(e.message) from e

        return flatten(data["response"])


class TeslemetryEnergySiteLiveCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching energy site live status from the Teslemetry API."""

    def __init__(self, hass: HomeAssistant, api: EnergySpecific) -> None:
        """Initialize Teslemetry Energy Site Live coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name="Teslemetry Energy Site Live",
            update_interval=ENERGY_LIVE_INTERVAL,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Update energy site data using Teslemetry API."""

        try:
            data = await self.api.live_status()
        except TeslaFleetError as e:
            raise UpdateFailed(e.message) from e

        # Convert Wall Connectors from array to dict
        data["response"]["wall_connectors"] = {
            wc["din"]: wc for wc in data["response"].get("wall_connectors", [])
        }

        return data["response"]


class TeslemetryEnergySiteInfoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching energy site info from the Teslemetry API."""

    def __init__(self, hass: HomeAssistant, api: EnergySpecific, product: dict) -> None:
        """Initialize Teslemetry Energy Info coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name="Teslemetry Energy Site Info",
            update_interval=ENERGY_INFO_INTERVAL,
        )
        self.api = api
        self.data = product

    async def _async_update_data(self) -> dict[str, Any]:
        """Update energy site data using Teslemetry API."""

        try:
            data = await self.api.site_info()
        except TeslaFleetError as e:
            raise UpdateFailed(e.message) from e

        return flatten(data["response"])
