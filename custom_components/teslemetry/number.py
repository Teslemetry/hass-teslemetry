"""Number platform for Teslemetry integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tesla_fleet_api.const import Scopes

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    PRECISION_WHOLE,
    UnitOfElectricCurrent,
    UnitOfSpeed,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import (
    TeslemetryVehicleEntity,
    TeslemetryEnergyInfoEntity,
)
from .models import TeslemetryVehicleData, TeslemetryEnergyData


@dataclass(frozen=True, kw_only=True)
class TeslemetryNumberEntityDescription(NumberEntityDescription):
    """Describes Teslemetry Number entity."""

    func: Callable
    native_min_value: float
    native_max_value: float
    min_key: str | None = None
    max_key: str | None = None
    scopes: list[Scopes] | None = None


VEHICLE_DESCRIPTIONS: tuple[TeslemetryNumberEntityDescription, ...] = (
    TeslemetryNumberEntityDescription(
        key="charge_state_charge_current_request",
        native_step=PRECISION_WHOLE,
        native_min_value=0,
        native_max_value=32,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        max_key="charge_state_charge_current_request_max",
        func=lambda api, value: api.set_charging_amps(int(value)),
        scopes=[Scopes.VEHICLE_CHARGING_CMDS],
    ),
    TeslemetryNumberEntityDescription(
        key="charge_state_charge_limit_soc",
        native_step=PRECISION_WHOLE,
        native_min_value=50,
        native_max_value=100,
        native_unit_of_measurement=PERCENTAGE,
        device_class=NumberDeviceClass.BATTERY,
        min_key="charge_state_charge_limit_soc_min",
        max_key="charge_state_charge_limit_soc_max",
        func=lambda api, value: api.set_charge_limit(int(value)),
        scopes=[Scopes.VEHICLE_CHARGING_CMDS, Scopes.VEHICLE_CMDS],
    ),
    TeslemetryNumberEntityDescription(
        key="vehicle_state_speed_limit_mode_current_limit_mph",
        native_step=PRECISION_WHOLE,
        native_min_value=50,
        native_max_value=120,
        native_unit_of_measurement=UnitOfSpeed.MILES_PER_HOUR,
        device_class=NumberDeviceClass.SPEED,
        mode=NumberMode.BOX,
        min_key="vehicle_state_speed_limit_mode_min_limit_mph",
        max_key="vehicle_state_speed_limit_mode_max_limit_mph",
        func=lambda api, value: api.speed_limit_set_limit(value),
        scopes=[Scopes.VEHICLE_CMDS],
    ),
)

ENERGY_INFO_DESCRIPTIONS: tuple[TeslemetryNumberEntityDescription, ...] = (
    TeslemetryNumberEntityDescription(
        key="backup_reserve_percent",
        native_step=PRECISION_WHOLE,
        native_min_value=0,
        native_max_value=100,
        native_unit_of_measurement=PERCENTAGE,
        scopes=[Scopes.ENERGY_CMDS],
        func=lambda api, value: api.backup(int(value)),
    ),
    TeslemetryNumberEntityDescription(
        # I have no examples of this
        key="off_grid_vehicle_charging_reserve",
        native_step=PRECISION_WHOLE,
        native_min_value=0,
        native_max_value=100,
        native_unit_of_measurement=PERCENTAGE,
        scopes=[Scopes.ENERGY_CMDS],
        func=lambda api, value: api.off_grid_vehicle_charging_reserve(int(value)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry sensor platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    # Add vehicle entities
    async_add_entities(
        TeslemetryVehicleNumberEntity(
            vehicle,
            description,
            any(scope in data.scopes for scope in description.scopes),
        )
        for vehicle in data.vehicles
        for description in VEHICLE_DESCRIPTIONS
    )

    # Add energy site entities
    async_add_entities(
        TeslemetryEnergyInfoNumberSensorEntity(
            energysite,
            description,
            any(scope in data.scopes for scope in description.scopes),
        )
        for energysite in data.energysites
        for description in ENERGY_INFO_DESCRIPTIONS
        if description.key in energysite.info_coordinator.data
    )


class TeslemetryNumberEntity(NumberEntity):
    """Base class for all Teslemetry number entities."""

    entity_description: TeslemetryNumberEntityDescription

    @property
    def native_value(self) -> float | None:
        """Return the value reported by the number."""
        return self.get()

    @property
    def native_min_value(self) -> float:
        """Return the minimum value."""
        if self.entity_description.min_key:
            return self.get(
                self.entity_description.min_key,
                self.entity_description.native_min_value,
            )
        return self.entity_description.native_min_value

    @property
    def native_max_value(self) -> float:
        """Return the maximum value."""
        if self.entity_description.max_key:
            return self.get(
                self.entity_description.max_key,
                self.entity_description.native_max_value,
            )
        return self.entity_description.native_max_value


class TeslemetryVehicleNumberEntity(TeslemetryVehicleEntity, TeslemetryNumberEntity):
    """Number entity for current charge."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetryNumberEntityDescription,
        scoped: bool,
    ) -> None:
        """Initialize the Number entity."""
        super().__init__(data, description.key)
        self.scoped = scoped
        self.entity_description = description

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        await self.entity_description.func(self.api, value)
        self.set((self.key, value))


class TeslemetryEnergyInfoNumberSensorEntity(
    TeslemetryEnergyInfoEntity, TeslemetryNumberEntity
):
    """Number entity for current charge."""

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: TeslemetryNumberEntityDescription,
        scoped: bool,
    ) -> None:
        """Initialize the Number entity."""
        super().__init__(data, description.key)
        self.scoped = scoped
        self.entity_description = description

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        self.raise_for_scope()
        await self.entity_description.func(self.api, value)
        self.set((self.key, value))
