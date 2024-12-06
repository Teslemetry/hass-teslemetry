"""Select platform for Teslemetry integration."""

from __future__ import annotations
from itertools import chain
from tesla_fleet_api.const import (
    Scope,
    Seat,
    EnergyExportMode,
    EnergyOperationMode,
)
from teslemetry_stream import TelemetryFields

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import TeslemetryHeaterOptions, TeslemetryTimestamp
from .entity import (
    TeslemetryVehicleEntity,
    TeslemetryEnergyInfoEntity,
)
from .models import TeslemetryEnergyData, TeslemetryVehicleData


@dataclass(frozen=True, kw_only=True)
class SeatHeaterDescription(SelectEntityDescription):
    """Seat Header entity description."""

    position: Seat
    avaliable_fn: callable
    timestamp_key: TeslemetryTimestamp | None = None
    streaming_key: TelemetryFields | None = None


SEAT_HEATER_DESCRIPTIONS: tuple[SeatHeaterDescription, ...] = (
    SeatHeaterDescription(
        key="climate_state_seat_heater_left",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        streaming_key=TelemetryFields.SEAT_HEATER_LEFT,
        position=Seat.FRONT_LEFT,
        avaliable_fn=lambda _: True,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_right",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        streaming_key=TelemetryFields.SEAT_HEATER_RIGHT,
        position=Seat.FRONT_RIGHT,
        avaliable_fn=lambda _: True,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_rear_left",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        streaming_key=TelemetryFields.SEAT_HEATER_REAR_LEFT,
        position=Seat.REAR_LEFT,
        avaliable_fn=lambda self: not self.exactly(
            "vehicle_config_rear_seat_heaters", 0
        ),
        entity_registry_enabled_default=False,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_rear_center",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        streaming_key=TelemetryFields.SEAT_HEATER_REAR_CENTER,
        position=Seat.REAR_CENTER,
        avaliable_fn=lambda self: not self.exactly(
            0, "vehicle_config_rear_seat_heaters"
        ),
        entity_registry_enabled_default=False,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_rear_right",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        streaming_key=TelemetryFields.SEAT_HEATER_REAR_RIGHT,
        position=Seat.REAR_RIGHT,
        avaliable_fn=lambda self: not self.exactly(
            0, "vehicle_config_rear_seat_heaters"
        ),
        entity_registry_enabled_default=False,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_third_row_left",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        position=Seat.THIRD_LEFT,
        avaliable_fn=lambda self: not self.exactly(
            "None", "vehicle_config_third_row_seats"
        ),
        entity_registry_enabled_default=False,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_third_row_right",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        position=Seat.THIRD_RIGHT,
        avaliable_fn=lambda self: not self.exactly(
            "None", "vehicle_config_third_row_seats"
        ),
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
                TeslemetrySeatHeaterSelectEntity(vehicle, description, scoped)
                for description in SEAT_HEATER_DESCRIPTIONS
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

class SelectRestoreEntity(SelectEntity, RestoreEntity):
    """Base class for Teslemetry Select Entities."""

    _attr_current_option = None

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None and not self.coordinator.updated_once:
            if (state.state in self._attr_options):
                self._attr_current_option = state.state


class TeslemetrySeatHeaterSelectEntity(TeslemetryVehicleEntity, SelectRestoreEntity):
    """Select entity for vehicle seat heater."""

    entity_description: SeatHeaterDescription

    _attr_options = [
        TeslemetryHeaterOptions.OFF,
        TeslemetryHeaterOptions.LOW,
        TeslemetryHeaterOptions.MEDIUM,
        TeslemetryHeaterOptions.HIGH,
    ]

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
            data, description.key, description.timestamp_key, description.streaming_key
        )

    def _async_update_attrs(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_available = self.entity_description.avaliable_fn(self)
        value = self._value
        if value is None:
            self._attr_current_option = None
        else:
            self._attr_current_option = self._attr_options[value]

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        self._attr_current_option = value

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        level = self._attr_options.index(option)
        # AC must be on to turn on seat heater
        if not self.get("climate_state_is_climate_on"):
            await self.handle_command(self.api.auto_conditioning_start())
        await self.handle_command(
            self.api.remote_seat_heater_request(self.entity_description.position, level)
        )
        self._attr_current_option = option
        self.async_write_ha_state()


class TeslemetryWheelHeaterSelectEntity(TeslemetryVehicleEntity, SelectRestoreEntity):
    """Select entity for vehicle steering wheel heater."""

    _attr_options = [
        TeslemetryHeaterOptions.OFF,
        TeslemetryHeaterOptions.LOW,
        TeslemetryHeaterOptions.HIGH,
    ]

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scoped: bool,
    ) -> None:
        """Initialize the vehicle seat select entity."""
        self.scoped = scoped
        super().__init__(
            data,
            "climate_state_steering_wheel_heat_level",
            TeslemetryTimestamp.CLIMATE_STATE,
        )

    def _async_update_attrs(self) -> None:
        """Handle updated data from the coordinator."""

        value = self._value
        if value is None:
            self._attr_current_option = None
        else:
            self._attr_current_option = self._attr_options[value]

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        level = self._attr_options.index(option)
        # AC must be on to turn on seat heater
        if not self.get("climate_state_is_climate_on"):
            await self.handle_command(self.api.auto_conditioning_start())
        await self.handle_command(
            self.api.remote_steering_wheel_heat_level_request(level)
        )
        self._attr_current_option = option
        self.async_write_ha_state()


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
