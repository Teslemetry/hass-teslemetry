"""Switch platform for Teslemetry integration."""

from __future__ import annotations
from itertools import chain
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tesla_fleet_api.const import Scope, Seat, TelemetryField

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TeslemetryTimestamp
from .entity import (
    TeslemetryVehicleEntity,
    TeslemetryEnergyInfoEntity,
    TeslemetryEnergyLiveEntity,
)
from .models import (
    TeslemetryVehicleData,
    TeslemetryEnergyData,
)


@dataclass(frozen=True, kw_only=True)
class TeslemetrySwitchEntityDescription(SwitchEntityDescription):
    """Describes Teslemetry Switch entity."""

    on_func: Callable
    off_func: Callable
    scopes: list[Scope] | None = None
    timestamp_key: TeslemetryTimestamp | None = None
    streaming_key: TelemetryField | None = None


VEHICLE_DESCRIPTIONS: tuple[TeslemetrySwitchEntityDescription, ...] = (
    TeslemetrySwitchEntityDescription(
        key="vehicle_state_sentry_mode",
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        streaming_key=TelemetryField.SENTRY_MODE,
        on_func=lambda api: api.set_sentry_mode(on=True),
        off_func=lambda api: api.set_sentry_mode(on=False),
        scopes=[Scope.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="vehicle_state_valet_mode",
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        on_func=lambda api: api.set_valet_mode(on=True),
        off_func=lambda api: api.set_valet_mode(on=False),
        scopes=[Scope.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_auto_seat_climate_left",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        streaming_key=TelemetryField.AUTO_SEAT_CLIMATE_LEFT,
        on_func=lambda api: api.remote_auto_seat_climate_request(Seat.FRONT_LEFT, True),
        off_func=lambda api: api.remote_auto_seat_climate_request(
            Seat.FRONT_LEFT, False
        ),
        scopes=[Scope.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_auto_seat_climate_right",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        streaming_key=TelemetryField.AUTO_SEAT_CLIMATE_RIGHT,
        on_func=lambda api: api.remote_auto_seat_climate_request(
            Seat.FRONT_RIGHT, True
        ),
        off_func=lambda api: api.remote_auto_seat_climate_request(
            Seat.FRONT_RIGHT, False
        ),
        scopes=[Scope.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_auto_steering_wheel_heat",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        on_func=lambda api: api.remote_auto_steering_wheel_heat_climate_request(
            on=True
        ),
        off_func=lambda api: api.remote_auto_steering_wheel_heat_climate_request(
            on=False
        ),
        scopes=[Scope.VEHICLE_CMDS],
    ),
)

VEHICLE_CHARGE_DESCRIPTIONS = TeslemetrySwitchEntityDescription(
    key="charge_state_user_charge_enable_request",
    streaming_key=TelemetryField.CHARGE_ENABLE_REQUEST,
    on_func=lambda api: api.charge_start(),
    off_func=lambda api: api.charge_stop(),
    scopes=[Scope.VEHICLE_CMDS, Scope.VEHICLE_CHARGING_CMDS],
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry Switch platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        chain(
            (
                TeslemetryVehicleSwitchEntity(vehicle, description, data.scopes)
                for vehicle in data.vehicles
                for description in VEHICLE_DESCRIPTIONS
            ),
            (
                TeslemetryChargeSwitchEntity(
                    vehicle, VEHICLE_CHARGE_DESCRIPTIONS, data.scopes
                )
                for vehicle in data.vehicles
            ),
            (
                TeslemetryStormModeSwitchEntity(energysite, data.scopes)
                for energysite in data.energysites
                if energysite.info_coordinator.data.get("storm_mode_capable")
            ),
            (
                TeslemetryChargeFromGridSwitchEntity(
                    energysite,
                    data.scopes,
                )
                for energysite in data.energysites
                if energysite.info_coordinator.data.get("components_battery")
                and energysite.info_coordinator.data.get("components_solar")
            ),
        )
    )


class TeslemetrySwitchEntity(SwitchEntity):
    """Base class for all Teslemetry switch entities."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    entity_description: TeslemetrySwitchEntityDescription


class TeslemetryVehicleSwitchEntity(TeslemetryVehicleEntity, TeslemetrySwitchEntity):
    """Base class for Teslemetry vehicle switch entities."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetrySwitchEntityDescription,
        scopes: list[Scope],
    ) -> None:
        """Initialize the Switch."""
        super().__init__(
            data, description.key, description.timestamp_key, description.streaming_key
        )
        self.entity_description = description
        self.scoped = any(scope in scopes for scope in description.scopes)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_is_on = self._value

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        self._attr_is_on = value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the Switch."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        await self.handle_command(self.entity_description.on_func(self.api))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the Switch."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        await self.handle_command(self.entity_description.off_func(self.api))
        self._attr_is_on = False
        self.async_write_ha_state()


class TeslemetryChargeSwitchEntity(TeslemetryVehicleSwitchEntity):
    """Entity class for Teslemetry Charge Switch."""

    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""
        if self._value is None:
            self._attr_is_on = self.get("charge_state_charge_enable_request")
        else:
            self._attr_is_on = self._value


class TeslemetryStormModeSwitchEntity(
    TeslemetryEnergyLiveEntity, TeslemetrySwitchEntity
):
    """Entity class for Storm Mode switch."""

    def __init__(
        self,
        data: TeslemetryEnergyData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the Switch."""
        super().__init__(data, "storm_mode_enabled")
        self.scoped = Scope.ENERGY_CMDS in scopes

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_is_on = self._value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the Switch."""
        self.raise_for_scope()
        await self.handle_command(self.api.storm_mode(enabled=True))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the Switch."""
        self.raise_for_scope()
        await self.handle_command(self.api.storm_mode(enabled=False))
        self._attr_is_on = False
        self.async_write_ha_state()


class TeslemetryChargeFromGridSwitchEntity(
    TeslemetryEnergyInfoEntity, TeslemetrySwitchEntity
):
    """Entity class for Charge From Grid switch."""

    def __init__(
        self,
        data: TeslemetryEnergyData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the Switch."""
        self.scoped = Scope.ENERGY_CMDS in scopes
        super().__init__(
            data, "components_disallow_charge_from_grid_with_solar_installed"
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""
        # When disallow_charge_from_grid_with_solar_installed is missing, its Off.
        # But this sensor is flipped to match how the Tesla app works.
        self._attr_is_on = not self.get(self.key, False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the Switch."""
        self.raise_for_scope()
        await self.handle_command(
            self.api.grid_import_export(
                disallow_charge_from_grid_with_solar_installed=False
            )
        )
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the Switch."""
        self.raise_for_scope()
        await self.handle_command(
            self.api.grid_import_export(
                disallow_charge_from_grid_with_solar_installed=True
            )
        )
        self._attr_is_on = False
        self.async_write_ha_state()
