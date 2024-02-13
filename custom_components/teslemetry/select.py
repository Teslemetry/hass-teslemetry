"""Select platform for Teslemetry integration."""
from __future__ import annotations

from tesla_fleet_api.const import Scope, Seat, EnergyExportMode, EnergyOperationMode

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TeslemetrySeatHeaterOptions
from .entity import (
    TeslemetryVehicleEntity,
    TeslemetryEnergyInfoEntity,
)
from .models import TeslemetryEnergyData, TeslemetryVehicleData


SEAT_HEATERS = {
    "climate_state_seat_heater_left": Seat.FRONT_LEFT,
    "climate_state_seat_heater_right": Seat.FRONT_RIGHT,
    "climate_state_seat_heater_rear_left": Seat.REAR_LEFT,
    "climate_state_seat_heater_rear_center": Seat.REAR_CENTER,
    "climate_state_seat_heater_rear_right": Seat.REAR_RIGHT,
    "climate_state_seat_heater_third_row_left": Seat.THIRD_LEFT,
    "climate_state_seat_heater_third_row_right": Seat.THIRD_RIGHT,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry select platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for vehicle in data.vehicles:
        scoped = Scope.VEHICLE_CMDS in data.scopes
        entities.append(
            TeslemetrySeatHeaterSelectEntity(
                vehicle, "climate_state_seat_heater_left", scoped
            )
        )
        entities.append(
            TeslemetrySeatHeaterSelectEntity(
                vehicle, "climate_state_seat_heater_right", scoped
            )
        )
        if vehicle.rear_seat_heaters:
            entities.append(
                TeslemetrySeatHeaterSelectEntity(
                    vehicle, "climate_state_seat_heater_rear_left", scoped
                )
            )
            entities.append(
                TeslemetrySeatHeaterSelectEntity(
                    vehicle, "climate_state_seat_heater_rear_center", scoped
                )
            )
            entities.append(
                TeslemetrySeatHeaterSelectEntity(
                    vehicle, "climate_state_seat_heater_rear_right", scoped
                )
            )
            if vehicle.third_row_seats:
                entities.append(
                    TeslemetrySeatHeaterSelectEntity(
                        vehicle, "climate_state_seat_heater_third_row_left", scoped
                    )
                )
                entities.append(
                    TeslemetrySeatHeaterSelectEntity(
                        vehicle, "climate_state_seat_heater_third_row_right", scoped
                    )
                )

    for energysite in data.energysites:
        if energysite.info_coordinator.data.get("components_battery"):
            # Requires battery
            entities.append(TeslemetryOperationSelectEntity(energysite, data.scopes))
            if energysite.info_coordinator.data.get("components_solar"):
                # Requires battery and solar
                entities.append(
                    TeslemetryExportRuleSelectEntity(energysite, data.scopes)
                )

    async_add_entities(entities)


class TeslemetrySeatHeaterSelectEntity(TeslemetryVehicleEntity, SelectEntity):
    """Select entity for vehicle seat heater."""

    _attr_options = [
        TeslemetrySeatHeaterOptions.OFF,
        TeslemetrySeatHeaterOptions.LOW,
        TeslemetrySeatHeaterOptions.MEDIUM,
        TeslemetrySeatHeaterOptions.HIGH,
    ]

    def __init__(self, data: TeslemetryVehicleData, key: str, scoped: bool) -> None:
        """Initialize the vehicle seat select entity."""
        super().__init__(data, key)
        self.scoped = scoped
        self.position = SEAT_HEATERS[key]

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        value = self.get()
        if value is None:
            return None
        return self._attr_options[value]

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        level = self._attr_options.index(option)
        # AC must be on to turn on seat heater
        if not self.get("climate_state_is_climate_on"):
            await self.handle_command(self.api.auto_conditioning_start())
        await self.handle_command(
            self.api.remote_seat_heater_request(self.position, level)
        )
        self.set((self.key, level))


class TeslemetryOperationSelectEntity(TeslemetryEnergyInfoEntity, SelectEntity):
    """Select entity for operation mode select entities."""

    _attr_options: list[str] = [
        EnergyOperationMode.AUTONOMOUS,
        EnergyOperationMode.BACKUP,
        EnergyOperationMode.SELF_CONSUMPTION,
    ]

    def __init__(
        self,
        data: TeslemetryEnergyData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the operation mode select entity."""
        super().__init__(data, "default_real_mode")
        self.scoped = Scope.ENERGY_CMDS in scopes

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self.get()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope()
        await self.handle_command(self.api.operation(option))
        self.set((self.key, option))


class TeslemetryExportRuleSelectEntity(TeslemetryEnergyInfoEntity, SelectEntity):
    """Select entity for export rules select entities."""

    _attr_options: list[str] = [
        EnergyExportMode.NEVER,
        EnergyExportMode.BATTERY_OK,
        EnergyExportMode.PV_ONLY,
    ]

    def __init__(
        self,
        data: TeslemetryEnergyData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the operation mode select entity."""
        super().__init__(data, "components_customer_preferred_export_rule")
        self.scoped = Scope.ENERGY_CMDS in scopes

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self.get(self.key, EnergyExportMode.NEVER)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope()
        await self.handle_command(
            self.api.grid_import_export(customer_preferred_export_rule=option)
        )
        self.set((self.key, option))
