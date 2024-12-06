"""Switch platform for Teslemetry integration."""

from __future__ import annotations
from itertools import chain
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tesla_fleet_api.const import Scope, Seat
from teslemetry_stream import TelemetryFields

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import TeslemetryTimestamp
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
    polling_value: Callable[[StateType], StateType] = bool
    streaming_key: TelemetryFields | None = None
    streaming_value: Callable[[StateType], StateType] = lambda x: x == "true"


VEHICLE_DESCRIPTIONS: tuple[TeslemetrySwitchEntityDescription, ...] = (
    TeslemetrySwitchEntityDescription(
        key="vehicle_state_sentry_mode",
        timestamp_key=TeslemetryTimestamp.VEHICLE_STATE,
        streaming_key=TelemetryFields.SENTRY_MODE,
        on_func=lambda api: api.set_sentry_mode(on=True),
        off_func=lambda api: api.set_sentry_mode(on=False),
        scopes=[Scope.VEHICLE_CMDS],
        streaming_value=lambda x: x != "Off",
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
        streaming_key=TelemetryFields.AUTO_SEAT_CLIMATE_LEFT,
        on_func=lambda api: api.remote_auto_seat_climate_request(Seat.FRONT_LEFT, True),
        off_func=lambda api: api.remote_auto_seat_climate_request(
            Seat.FRONT_LEFT, False
        ),
        scopes=[Scope.VEHICLE_CMDS],
    ),
    TeslemetrySwitchEntityDescription(
        key="climate_state_auto_seat_climate_right",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        streaming_key=TelemetryFields.AUTO_SEAT_CLIMATE_RIGHT,
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
    TeslemetrySwitchEntityDescription(
        key="climate_state_defrost_mode",
        timestamp_key=TeslemetryTimestamp.CLIMATE_STATE,
        on_func=lambda api: api.set_preconditioning_max(on=True, manual_override=False),
        off_func=lambda api: api.set_preconditioning_max(
            on=False, manual_override=False
        ),
        scopes=[Scope.VEHICLE_CMDS],
    ),
)

VEHICLE_CHARGE_DESCRIPTION = TeslemetrySwitchEntityDescription(
    key="charge_state_user_charge_enable_request",
    streaming_key=TelemetryFields.CHARGE_ENABLE_REQUEST,
    on_func=lambda api: api.charge_start(),
    off_func=lambda api: api.charge_stop(),
    scopes=[Scope.VEHICLE_CMDS, Scope.VEHICLE_CHARGING_CMDS],
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry Switch platform from a config entry."""


    async_add_entities(
        chain(
            (
                TeslemetryVehicleSwitchEntity(vehicle, description, entry.runtime_data.scopes)
                for vehicle in entry.runtime_data.vehicles
                for description in VEHICLE_DESCRIPTIONS
            ),
            (
                TeslemetryChargeSwitchEntity(
                    vehicle, VEHICLE_CHARGE_DESCRIPTION, entry.runtime_data.scopes
                )
                for vehicle in entry.runtime_data.vehicles
            ),
            (
                TeslemetryStormModeSwitchEntity(energysite, entry.runtime_data.scopes)
                for energysite in entry.runtime_data.energysites
                if energysite.info_coordinator.data.get("components_storm_mode_capable")
            ),
            (
                TeslemetryChargeFromGridSwitchEntity(
                    energysite,
                    entry.runtime_data.scopes,
                )
                for energysite in entry.runtime_data.energysites
                if energysite.info_coordinator.data.get("components_battery")
                and energysite.info_coordinator.data.get("components_solar")
            ),
        )
    )


class TeslemetrySwitchEntity(SwitchEntity):
    """Base class for all Teslemetry switch entities."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    entity_description: TeslemetrySwitchEntityDescription




class TeslemetryVehicleSwitchEntity(TeslemetryVehicleEntity, TeslemetrySwitchEntity, RestoreEntity):
    """Base class for Teslemetry vehicle switch entities."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetrySwitchEntityDescription,
        scopes: list[Scope],
    ) -> None:
        """Initialize the Switch."""

        self.entity_description = description
        self.scoped = any(scope in scopes for scope in description.scopes)

        super().__init__(
            data, description.key, description.timestamp_key, description.streaming_key
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None and not self.coordinator.updated_once:
            if (state.state == "on"):
                self._attr_is_on = True
            elif (state.state == "off"):
                self._attr_is_on = False

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_is_on = self.entity_description.polling_value(self._value)

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        self._attr_is_on = self.entity_description.streaming_value(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the Switch."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.entity_description.on_func(self.api))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the Switch."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
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

    # Need to test how streaming impacts this entity


class TeslemetryStormModeSwitchEntity(
    TeslemetryEnergyInfoEntity, TeslemetrySwitchEntity
):
    """Entity class for Storm Watch switch."""

    def __init__(
        self,
        data: TeslemetryEnergyData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the Switch."""
        super().__init__(data, "user_settings_storm_mode_enabled")
        self.scoped = Scope.ENERGY_CMDS in scopes

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_is_on = self._value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the Switch."""
        self.raise_for_scope(Scope.ENERGY_CMDS)
        await self.handle_command(self.api.storm_mode(enabled=True))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the Switch."""
        self.raise_for_scope(Scope.ENERGY_CMDS)
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
        self.raise_for_scope(Scope.ENERGY_CMDS)
        await self.handle_command(
            self.api.grid_import_export(
                disallow_charge_from_grid_with_solar_installed=False
            )
        )
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the Switch."""
        self.raise_for_scope(Scope.ENERGY_CMDS)
        await self.handle_command(
            self.api.grid_import_export(
                disallow_charge_from_grid_with_solar_installed=True
            )
        )
        self._attr_is_on = False
        self.async_write_ha_state()
