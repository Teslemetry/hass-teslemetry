"""Teslemetry Data Coordinator."""

from datetime import timedelta
from time import time
from typing import Any
from random import randint

from tesla_fleet_api import EnergySpecific, Teslemetry
from tesla_fleet_api.const import VehicleDataEndpoint
from tesla_fleet_api.exceptions import (
    TeslaFleetError,
    InvalidToken,
    SubscriptionRequired,
    Forbidden,
    LoginRequired,
    InternalServerError,
    ServiceUnavailable,
    GatewayTimeout,
    DeviceUnexpectedResponse
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from .const import LOGGER, DOMAIN, ENERGY_HISTORY_FIELDS
from .helpers import flatten

VEHICLE_INTERVAL = timedelta(minutes=15)
ENERGY_LIVE_INTERVAL = timedelta(seconds=30)
ENERGY_INFO_INTERVAL = timedelta(seconds=30)
ENERGY_HISTORY_INTERVAL = timedelta(minutes=5)


ENDPOINTS = [
    VehicleDataEndpoint.CHARGE_STATE,
    VehicleDataEndpoint.CLIMATE_STATE,
    VehicleDataEndpoint.DRIVE_STATE,
    VehicleDataEndpoint.LOCATION_DATA,
    VehicleDataEndpoint.VEHICLE_STATE,
    VehicleDataEndpoint.VEHICLE_CONFIG,
]




class TeslemetryVehicleDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching data from the Teslemetry API."""

    def __init__(
        self, hass: HomeAssistant, api: Teslemetry, product: dict
    ) -> None:
        """Initialize Teslemetry Vehicle Update Coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"Teslemetry Vehicle {product["vin"]}",
            update_interval=VEHICLE_INTERVAL,
        )
        self.api = api
        self.data = flatten(product)
        self.vin = product["vin"]

    async def _async_update_data(self) -> dict[str, Any]:
        """Update vehicle data using Teslemetry API."""


        try:
            data = (await self.api.vehicle_data_cached(self.vin, ENDPOINTS))["response"]
        except InvalidToken as e:
            raise ConfigEntryAuthFailed from e
        except (SubscriptionRequired,Forbidden,LoginRequired) as e:
            async_create_issue(
                self.hass,
                DOMAIN,
                self.api.vin,
                data=self.config_entry.entry_id,
                is_fixable=False,
                is_persistent=False,
                severity=IssueSeverity.ERROR,
                translation_key=e.key.lower()
                #translation_placeholders={"error": e.message}
            )
            raise UpdateFailed(e.message) from e
        except TeslaFleetError as e:
            raise UpdateFailed(e.message) from e
        except TypeError as e:
            raise UpdateFailed("Invalid response from Teslemetry") from e

        self.hass.bus.fire("teslemetry_vehicle_data", data)

        return flatten(data)


class TeslemetryEnergySiteLiveCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching energy site live status from the Teslemetry API."""

    failures: int = 0

    def __init__(self, hass: HomeAssistant, api: EnergySpecific) -> None:
        """Initialize Teslemetry Energy Site Live coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"Teslemetry Energy Site Live {api.energy_site_id}",
            update_interval=ENERGY_LIVE_INTERVAL,
        )
        self.api = api


    async def _async_update_data(self) -> dict[str, Any]:
        """Update energy site data using Teslemetry API."""

        try:
            data = (await self.api.live_status())["response"]
        except InvalidToken as e:
            raise ConfigEntryAuthFailed from e
        except (InternalServerError, ServiceUnavailable, GatewayTimeout, DeviceUnexpectedResponse) as e:
            self.failures += 1
            if self.failures > 2:
                raise UpdateFailed("Multiple 5xx failures") from e
            return self.data
        except TeslaFleetError as e:
            raise UpdateFailed(e.message) from e
        except TypeError as e:
            raise UpdateFailed("Invalid response from Teslemetry") from e

        # If the data isnt valid, placeholder it for safety
        if(not isinstance(data, dict)):
            return {}

        self.hass.bus.fire("teslemetry_live_status", data)

        # Convert Wall Connectors from array to dict
        if isinstance(data.get("wall_connectors"),list):
            data["wall_connectors"] = {
                wc["din"]: wc for wc in data["wall_connectors"]
            }
        else:
            data["wall_connectors"] = {}

        return data


class TeslemetryEnergySiteInfoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching energy site info from the Teslemetry API."""

    failures: int = 0

    def __init__(self, hass: HomeAssistant, api: EnergySpecific, product: dict) -> None:
        """Initialize Teslemetry Energy Info coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"Teslemetry Energy Site Info {api.energy_site_id}",
            update_interval=ENERGY_INFO_INTERVAL,
        )
        self.api = api
        self.data = product

    async def _async_update_data(self) -> dict[str, Any]:
        """Update energy site data using Teslemetry API."""

        try:
            data = (await self.api.site_info())["response"]
        except InvalidToken as e:
            raise ConfigEntryAuthFailed from e
        except (InternalServerError, ServiceUnavailable, GatewayTimeout, DeviceUnexpectedResponse) as e:
            self.failures += 1
            if self.failures > 2:
                raise UpdateFailed("Multiple 5xx failures") from e
            return self.data
        except TeslaFleetError as e:
            raise UpdateFailed(e.message) from e
        except TypeError as e:
            raise UpdateFailed("Invalid response from Teslemetry") from e

        # If the data isnt valid, placeholder it for safety
        if(not isinstance(data, dict)):
            data = {}

        self.hass.bus.fire("teslemetry_site_info", data)

        return flatten(data)

class TeslemetryEnergyHistoryCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching energy site info from the Teslemetry API."""

    failures: int = 0

    def __init__(self, hass: HomeAssistant, api: EnergySpecific) -> None:
        """Initialize Teslemetry Energy Info coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"Teslemetry Energy History {api.energy_site_id}",
            update_interval=ENERGY_HISTORY_INTERVAL,
        )
        self.api = api
        self.data = {key: 0 for key in ENERGY_HISTORY_FIELDS}

    async def async_config_entry_first_refresh(self) -> None:
        """Set up the data coordinator."""
        await super().async_config_entry_first_refresh()

        # Calculate seconds until next 5 minute period plus a random delay
        delta = randint(310, 330) - (int(time()) % 300)
        self.logger.debug("Scheduling next %s refresh in %s seconds", self.name, delta)
        self.update_interval = timedelta(seconds=delta)
        self._schedule_refresh()
        self.update_interval = ENERGY_HISTORY_INTERVAL


    async def _async_update_data(self) -> dict[str, Any]:
        """Update energy site data using Teslemetry API."""

        try:
            data = (await self.api.energy_history("day"))["response"]
        except InvalidToken as e:
            raise ConfigEntryAuthFailed from e
        except (InternalServerError, ServiceUnavailable, GatewayTimeout, DeviceUnexpectedResponse) as e:
            # Allow the coordinator to be slightly fault tolerant
            self.failures += 1
            if self.failures > 2:
                raise UpdateFailed("Multiple 5xx failures") from e
            #self.update_interval(ENERGY_HISTORY_INTERVAL)
            return self.data
        except TeslaFleetError as e:
            raise UpdateFailed(e.message) from e
        except TypeError as e:
            raise UpdateFailed("Invalid response from Teslemetry") from e

        # Add all time periods together
        output = {key: 0 for key in ENERGY_HISTORY_FIELDS}
        for period in data.get("time_series",[]):
            for key in ENERGY_HISTORY_FIELDS:
                output[key] += period.get(key,0)

        return output
