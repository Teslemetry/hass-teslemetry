"""Select platform for Teslemetry integration."""
from __future__ import annotations

from tesla_fleet_api.const import Scopes

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TeslemetrySeatHeaterOptions
from .entity import (
    TeslemetryVehicleEntity,
    TeslemetryEnergySiteInfoEntity,
)

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
        TeslemetrySeatHeaterSelectEntity(
            vehicle, key, Scopes.VEHICLE_CMDS in data.scopes
        )
        for vehicle in data.vehicles
        for key in SEAT_HEATERS
    )

    async_add_entities(
        klass(
            energysite, Scopes.ENERGY_CMDS in data.scopes
        )
        for klass in (TeslemetryOperationMode,TeslemetryGridMode)
        for energysite in data.energysites
    )

class TeslemetrySelectEntity(SelectEntity):
    """Base class for Teslemetry select entities."""

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return super().available and self.has()

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self.get()


class TeslemetrySeatHeaterSelectEntity(TeslemetryVehicleEntity, TeslemetrySelectEntity):
    """Select entity for vehicle seat heater."""

    _attr_options = [
        TeslemetrySeatHeaterOptions.OFF,
        TeslemetrySeatHeaterOptions.LOW,
        TeslemetrySeatHeaterOptions.MEDIUM,
        TeslemetrySeatHeaterOptions.HIGH,
    ]

    def __init__(self, vehicle, key, scoped: bool) -> None:
        """Initialize the vehicle seat select entity."""
        super().__init__(vehicle, key)
        self.scoped = scoped

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self._attr_options[self.get()]

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        level = self._attr_options.index(option)
        await self.api.remote_seat_heater_request(SEAT_HEATERS[self.key], level)
        self.set((self.key, level))

class TeslemetryOperationMode(TeslemetryEnergySiteInfoEntity, TeslemetrySelectEntity):
    """Select entity for energy site operation mode."""

    _attr_options = [
        "autonomous",
        "self_consumption",
        "backup"
    ]

    def __init__(self, vehicle, scoped: bool) -> None:
        """Initialize the operation mode select entity."""
        super().__init__(vehicle, "default_real_mode")
        self.scoped = scoped

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        await self.api.operation(option)
        self.set((self.key, option))

class TeslemetryGridMode(TeslemetryEnergySiteInfoEntity, TeslemetrySelectEntity):
    """Select entity for energy site grid mode."""

    _attr_options = [
        "battery_ok",
        "pv_only",
        "never"
    ]

    def __init__(self, vehicle, scoped: bool) -> None:
        """Initialize the grid mode select entity."""
        super().__init__(vehicle, "customer_preferred_export_rule")
        self.scoped = scoped

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        await self.api.grid_import_export(customer_preferred_export_rule=option)
        self.set((self.key, option))