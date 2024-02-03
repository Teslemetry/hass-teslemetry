"""Switch platform for Teslemetry integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tesla_fleet_api.const import Scopes

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import (
    TeslemetryVehicleEntity,
)
from .models import TeslemetryVehicleData


@dataclass(frozen=True, kw_only=True)
class TeslemetrySwitchEntityDescription(SwitchEntityDescription):
    """Describes Teslemetry Switch entity."""

    on_func: Callable
    off_func: Callable
    scopes: list[Scopes] | None = None


DESCRIPTIONS: tuple[TeslemetrySwitchEntityDescription, ...] = (
    TeslemetrySwitchEntityDescription(
        key="charge_state_charge_enable_request",
        on_func=lambda api: api.start_charging(),
        off_func=lambda api: api.stop_charging(),
        scopes=[Scopes.VEHICLE_CMDS,Scopes.VEHICLE_CHARGING_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="vehicle_state_sentry_mode",
        on_func=lambda api: api.set_sentry_mode(on=True),
        off_func=lambda api: api.set_sentry_mode(on=False),
        scopes=[Scopes.VEHICLE_CMDS]
    ),
    TeslemetrySwitchEntityDescription(
        key="vehicle_state_valet_mode",
        on_func=lambda api: api.set_valet_mode(on=True),
        off_func=lambda api: api.set_valet_mode(on=False),
        scopes=[Scopes.VEHICLE_CMDS]
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_auto_seat_climate_left",
        on_func=lambda api: api.remote_auto_seat_climate_request(0,True),
        off_func=lambda api: api.remote_auto_seat_climate_request(0,False),
        scopes=[Scopes.VEHICLE_CMDS]
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_auto_seat_climate_right",
        on_func=lambda api: api.remote_auto_seat_climate_request(1,True),
        off_func=lambda api: api.remote_auto_seat_climate_request(1,False),
        scopes=[Scopes.VEHICLE_CMDS]
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_auto_steering_wheel_heat",
        on_func=lambda api: api.remote_auto_steering_wheel_heat_climate_request(on=True),
        off_func=lambda api: api.remote_auto_steering_wheel_heat_climate_request(on=False),
        scopes=[Scopes.VEHICLE_CMDS]
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry Switch platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            TeslemetrySwitchEntity(vehicle, description)
            for vehicle in data.vehicles
            for description in DESCRIPTIONS
        ]
    )


class TeslemetrySwitchEntity(TeslemetryVehicleEntity, SwitchEntity):
    """Base class for Teslemetry Switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    entity_description: TeslemetrySwitchEntityDescription

    def __init__(
        self,
        vehicle: TeslemetryVehicleData,
        description: TeslemetrySwitchEntityDescription,
    ) -> None:
        """Initialize the Switch."""
        super().__init__(vehicle, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return super().available and self.has()

    @property
    def is_on(self) -> bool:
        """Return the state of the Switch."""
        return self.get()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the Switch."""
        await self.entity_description.on_func(self.api)
        self.set((self.entity_description.key, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the Switch."""
        await self.entity_description.off_func(self.api)
        self.set((self.entity_description.key, False))
