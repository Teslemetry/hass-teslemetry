"""Button platform for Teslemetry integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tesla_fleet_api.const import Scopes

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TeslemetryState
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


@dataclass(frozen=True, kw_only=True)
class TeslemetryButtonEntityDescription(ButtonEntityDescription):
    """Describes a Teslemetry Button entity."""

    func: Callable


DESCRIPTIONS: tuple[TeslemetryButtonEntityDescription, ...] = (
    TeslemetryButtonEntityDescription(
        key="wake", func=lambda api: api.wake_up(), icon="mdi:sleep-off"
    ),
    TeslemetryButtonEntityDescription(
        key="flash_lights", func=lambda api: api.flash_lights(), icon="mdi:flashlight"
    ),
    TeslemetryButtonEntityDescription(
        key="honk", func=lambda api: api.honk_horn(), icon="mdi:bullhorn"
    ),
    TeslemetryButtonEntityDescription(
        key="enable_keyless_driving",
        func=lambda api: api.remote_start_drive(),
        icon="mdi:car-key",
    ),
    TeslemetryButtonEntityDescription(
        key="boombox", func=lambda api: api.remote_boombox(0), icon="mdi:volume-high"
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry Button platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        TeslemetryButtonEntity(vehicle, description)
        for vehicle in data.vehicles
        for description in DESCRIPTIONS
        if Scopes.VEHICLE_CMDS in data.scopes
    )


class TeslemetryButtonEntity(TeslemetryVehicleEntity, ButtonEntity):
    """Base class for Teslemetry buttons."""

    entity_description: TeslemetryButtonEntityDescription

    def __init__(
        self,
        vehicle: TeslemetryVehicleData,
        description: TeslemetryButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(vehicle, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Press the button."""
        await self.entity_description.func(self.api)
