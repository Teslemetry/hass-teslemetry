"""Select platform for Teslemetry integration."""
from __future__ import annotations

from tesla_fleet_api.const import Scopes

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TeslemetrySeatHeaterOptions
from .entity import (
    TeslemetryEnergyEntity,
    TeslemetryVehicleEntity,
    TeslemetryWallConnectorEntity,
)
from .coordinator import (
    TeslemetryEnergyDataCoordinator,
    TeslemetryVehicleDataCoordinator,
)
from .models import TeslemetryEnergyData, TeslemetryVehicleData

SEAT_HEATERS = {
    "climate_state_seat_heater_left": "front_left",
    "climate_state_seat_heater_right": "front_right",
    "climate_state_seat_heater_rear_left": "rear_left",
    "climate_state_seat_heater_rear_center": "rear_center",
    "climate_state_seat_heater_rear_right": "rear_right",
    "climate_state_seat_heater_third_row_left": "third_row_left",
    "climate_state_seat_heater_third_row_right": "third_row_right",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry select platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        TeslemetrySeatHeaterSelectEntity(vehicle, key)
        for vehicle in data.vehicles
        for key in SEAT_HEATERS
    )


class TeslemetrySeatHeaterSelectEntity(TeslemetryVehicleEntity, SelectEntity):
    """Select entity for current charge."""

    _attr_options = [
        TeslemetrySeatHeaterOptions.OFF,
        TeslemetrySeatHeaterOptions.LOW,
        TeslemetrySeatHeaterOptions.MEDIUM,
        TeslemetrySeatHeaterOptions.HIGH,
    ]

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return super().available and self.has()

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self._attr_options[self.get()]

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        level = self._attr_options.index(option)
        await self.api.remote_seat_heater_request(SEAT_HEATERS[self.key], level)
        self.set((self.key, level))
