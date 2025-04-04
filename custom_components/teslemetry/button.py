"""Button platform for Teslemetry integration."""

from __future__ import annotations
from itertools import chain

from collections.abc import Callable
from dataclasses import dataclass

from tesla_fleet_api.const import Scope

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import (
    TeslemetryVehicleEntity,
)
from .models import TeslemetryVehicleData
from .helpers import handle_vehicle_command, handle_command


@dataclass(frozen=True, kw_only=True)
class TeslemetryButtonEntityDescription(ButtonEntityDescription):
    """Describes a Teslemetry Button entity."""

    func: Callable | None = None


DESCRIPTIONS: tuple[TeslemetryButtonEntityDescription, ...] = (
    TeslemetryButtonEntityDescription(key="wake",
        func=lambda self: handle_command(self.api.wake_up())),
    TeslemetryButtonEntityDescription(
        key="flash_lights", func=lambda self: handle_vehicle_command(self.api.flash_lights())
    ),
    TeslemetryButtonEntityDescription(
        key="honk", func=lambda self: handle_vehicle_command(self.api.honk_horn())
    ),
    TeslemetryButtonEntityDescription(
        key="boombox", func=lambda self: handle_vehicle_command(self.api.remote_boombox(0))
    ),
    TeslemetryButtonEntityDescription(
        key="homelink",
        func=lambda self: handle_vehicle_command(self.api.trigger_homelink(
            lat=self.coordinator.data["drive_state_latitude"],
            lon=self.coordinator.data["drive_state_longitude"],
        )),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry Button platform from a config entry."""


    async_add_entities(
        chain(
            (
                TeslemetryButtonEntity(vehicle, description)
                for vehicle in entry.runtime_data.vehicles
                for description in DESCRIPTIONS
                if Scope.VEHICLE_CMDS in entry.runtime_data.scopes
            ),
            (TeslemetryRefreshButtonEntity(vehicle) for vehicle in entry.runtime_data.vehicles),
        )
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
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""

    async def async_press(self) -> None:
        """Press the button."""

        await self.entity_description.func(self)


class TeslemetryRefreshButtonEntity(TeslemetryVehicleEntity, ButtonEntity):
    """Force Refresh entity for Teslemetry."""

    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        data: TeslemetryVehicleData,
    ) -> None:
        """Initialize the button."""
        super().__init__(data, "refresh")

    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""

    async def async_press(self) -> None:
        """Press the button."""

        await self.coordinator.async_request_refresh()
