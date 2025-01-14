"""Select platform for Teslemetry integration."""

from __future__ import annotations
from collections.abc import Callable
from itertools import chain
from tesla_fleet_api.const import (
    Scope,
    Seat,
    EnergyExportMode,
    EnergyOperationMode,
)
from teslemetry_stream import Signal

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import TeslemetryHeaterOptions
from .entity import (
    TeslemetryVehicleEntity,
    TeslemetryEnergyInfoEntity,
    TeslemetryVehicleStreamSingleEntity,
)
from .models import TeslemetryEnergyData, TeslemetryVehicleData


@dataclass(frozen=True, kw_only=True)
class SeatHeaterDescription(SelectEntityDescription):
    """Seat Header entity description."""

    position: Seat
    supported_fn: Callable = lambda _: True
    streaming_key: Signal | None = None


SEAT_HEATER_DESCRIPTIONS: tuple[SeatHeaterDescription, ...] = (
    SeatHeaterDescription(
        key="climate_state_seat_heater_left",
        streaming_key=Signal.SEAT_HEATER_LEFT,
        position=Seat.FRONT_LEFT,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_right",
        streaming_key=Signal.SEAT_HEATER_RIGHT,
        position=Seat.FRONT_RIGHT,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_rear_left",
        streaming_key=Signal.SEAT_HEATER_REAR_LEFT,
        position=Seat.REAR_LEFT,
        supported_fn=lambda data: data.get(
            "vehicle_config_rear_seat_heaters"
        ) != 0,
        entity_registry_enabled_default=False,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_rear_center",
        streaming_key=Signal.SEAT_HEATER_REAR_CENTER,
        position=Seat.REAR_CENTER,
        supported_fn=lambda data: data.get(
            "vehicle_config_rear_seat_heaters"
        ) != 0,
        entity_registry_enabled_default=False,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_rear_right",
        streaming_key=Signal.SEAT_HEATER_REAR_RIGHT,
        position=Seat.REAR_RIGHT,
        supported_fn=lambda data: data.get(
            "vehicle_config_rear_seat_heaters"
        ) != 0,
        entity_registry_enabled_default=False,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_third_row_left",
        position=Seat.THIRD_LEFT,
        supported_fn=lambda data: data.get(
            "vehicle_config_third_row_seats"
        ) != "None",
        entity_registry_enabled_default=False,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_third_row_right",
        position=Seat.THIRD_RIGHT,
        supported_fn=lambda data: data.get(
            "vehicle_config_third_row_seats"
        ) != "None",
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry select platform from a config entry."""


    scoped = Scope.VEHICLE_CMDS in entry.runtime_data.scopes

    async_add_entities(
        chain(
            (
                TeslemetryPollingSeatHeaterSelectEntity(vehicle, description, scoped)
                if vehicle.api.pre2021 or vehicle.firmware < "2024.26" or description.streaming_key is None
                else TeslemetryStreamingSeatHeaterSelectEntity(vehicle, description, scoped)
                for description in SEAT_HEATER_DESCRIPTIONS
                for vehicle in entry.runtime_data.vehicles
                if description.supported_fn(vehicle.coordinator.data)
            ),
            (
                TeslemetrPollingWheelHeaterSelectEntity(vehicle, scoped)
                if vehicle.api.pre2021 or vehicle.firmware < "2024.44.25"
                else TeslemetryStreamingWheelHeaterSelectEntity(vehicle, scoped)
                for vehicle in entry.runtime_data.vehicles
            ),
            (
                TeslemetryOperationSelectEntity(energysite, entry.runtime_data.scopes)
                for energysite in entry.runtime_data.energysites
                if energysite.info_coordinator.data.get("components_battery")
            ),
            (
                TeslemetryExportRuleSelectEntity(energysite, entry.runtime_data.scopes)
                for energysite in entry.runtime_data.energysites
                if energysite.info_coordinator.data.get("components_battery")
                and energysite.info_coordinator.data.get("components_solar")
            ),
        )
    )


class TeslemetrySeatHeaterSelectEntity(SelectEntity):
    """Select entity for vehicle seat heater."""

    entity_description: SeatHeaterDescription

    _attr_options = [
        TeslemetryHeaterOptions.OFF,
        TeslemetryHeaterOptions.LOW,
        TeslemetryHeaterOptions.MEDIUM,
        TeslemetryHeaterOptions.HIGH,
    ]

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        level = self._attr_options.index(option)
        # AC must be on to turn on seat heater
        if not self.get("climate_state_is_climate_on"):
            await self.handle_command(self.api.auto_conditioning_start())
        await self.handle_command(
            self.api.remote_seat_heater_request(self.entity_description.position, level)
        )
        self._attr_current_option = option
        self.async_write_ha_state()

class TeslemetryPollingSeatHeaterSelectEntity(TeslemetryVehicleEntity, TeslemetrySeatHeaterSelectEntity):
    """Select entity for vehicle seat heater."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: SeatHeaterDescription,
        scoped: bool,
    ) -> None:
        """Initialize the vehicle seat select entity."""
        self.entity_description = description
        self.scoped = scoped
        super().__init__(
            data, description.key
        )

    def _async_update_attrs(self) -> None:
        """Handle updated data from the coordinator."""
        value = self._value
        if isinstance(value, int):
            self._attr_current_option = self._attr_options[value]
        else:
            self._attr_current_option = None

class TeslemetryStreamingSeatHeaterSelectEntity(TeslemetryVehicleStreamSingleEntity, TeslemetrySeatHeaterSelectEntity, RestoreEntity):
    """Select entity for vehicle seat heater."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: SeatHeaterDescription,
        scoped: bool,
    ) -> None:
        """Initialize the vehicle seat select entity."""
        assert description.streaming_key
        super().__init__(
            data, description.key, description.streaming_key
        )
        self.entity_description = description
        self.scoped = scoped
        self._attr_current_option = None

    async def async_added_to_hass(self) -> None:
            """Handle entity which will be added."""
            await super().async_added_to_hass()
            if (state := await self.async_get_last_state()) is not None:
                if (state.state in self._attr_options):
                    self._attr_current_option = state.state

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        if isinstance(value, int):
            self._attr_current_option = self._attr_options[value]
        else:
            self._attr_current_option = None


class TeslemetryWheelHeaterSelectEntity(SelectEntity):
    """Select entity for vehicle steering wheel heater."""

    _attr_options = [
        TeslemetryHeaterOptions.OFF,
        TeslemetryHeaterOptions.LOW,
        TeslemetryHeaterOptions.HIGH,
    ]

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        level = self._attr_options.index(option)
        # AC must be on to turn on seat heater
        if not self.get("climate_state_is_climate_on"):
            await self.handle_command(self.api.auto_conditioning_start())
        await self.handle_command(
            self.api.remote_steering_wheel_heat_level_request(level)
        )
        self._attr_current_option = option
        self.async_write_ha_state()

class TeslemetrPollingWheelHeaterSelectEntity(TeslemetryVehicleEntity, TeslemetryWheelHeaterSelectEntity):
    """Select entity for vehicle steering wheel heater."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scoped: bool,
    ) -> None:
        """Initialize the vehicle seat select entity."""
        super().__init__(
            data,
            "climate_state_steering_wheel_heat_level",
        )
        self.scoped = scoped

    def _async_update_attrs(self) -> None:
        """Handle updated data from the coordinator."""
        value = self._value
        if isinstance(value, int):
            self._attr_current_option = self._attr_options[value]
        else:
            self._attr_current_option = None

class TeslemetryStreamingWheelHeaterSelectEntity(TeslemetryVehicleStreamSingleEntity, TeslemetryWheelHeaterSelectEntity):
    """Select entity for vehicle steering wheel heater."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scoped: bool,
    ) -> None:
        """Initialize the vehicle seat select entity."""
        super().__init__(
            data,
            "climate_state_steering_wheel_heat_level",
            Signal.HVAC_STEERING_WHEEL_HEAT_LEVEL,
        )
        self.scoped = scoped
        self._attr_current_option = None

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        if isinstance(value, int):
            self._attr_current_option = self._attr_options[value]
        else:
            self._attr_current_option = None


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
        self.scoped = Scope.ENERGY_CMDS in scopes
        super().__init__(data, "default_real_mode")

    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""
        self._attr_current_option = self._value

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope(Scope.ENERGY_CMDS)
        await self.handle_command(self.api.operation(option))
        self._attr_current_option = option
        self.async_write_ha_state()


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
        self.scoped = Scope.ENERGY_CMDS in scopes
        super().__init__(data, "components_customer_preferred_export_rule")

    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""
        self._attr_current_option = self.get(self.key, EnergyExportMode.NEVER.value)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope(Scope.ENERGY_CMDS)
        await self.handle_command(
            self.api.grid_import_export(customer_preferred_export_rule=option)
        )
        self._attr_current_option = option
        self.async_write_ha_state()
