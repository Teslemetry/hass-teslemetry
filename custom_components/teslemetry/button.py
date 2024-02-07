"""Button platform for Teslemetry integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tesla_fleet_api.const import Scopes

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import (
    TeslemetryVehicleEntity,
)
from .models import TeslemetryVehicleData


@dataclass(frozen=True, kw_only=True)
class TeslemetryButtonEntityDescription(ButtonEntityDescription):
    """Describes a Teslemetry Button entity."""

    func: Callable | None = None


DESCRIPTIONS: tuple[TeslemetryButtonEntityDescription, ...] = (
    TeslemetryButtonEntityDescription(key="wake"),  # Every button runs wakeup
    TeslemetryButtonEntityDescription(
        key="flash_lights", func=lambda api: api.flash_lights()
    ),
    TeslemetryButtonEntityDescription(key="honk", func=lambda api: api.honk_horn()),
    TeslemetryButtonEntityDescription(
        key="enable_keyless_driving", func=lambda api: api.remote_start_drive()
    ),
    TeslemetryButtonEntityDescription(
        key="boombox", func=lambda api: api.remote_boombox(0)
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
        data: TeslemetryVehicleData,
        description: TeslemetryButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(data, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Press the button."""
        await self.wake_up_if_asleep()
        if self.entity_description.func:
            await self.entity_description.func(self.api)
