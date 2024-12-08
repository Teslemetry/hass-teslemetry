"""Lock platform for Teslemetry integration."""
from __future__ import annotations
from tesla_fleet_api.const import Scope
from typing import Any

from teslemetry_stream import Signal

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import ATTR_CODE
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, TeslemetryChargeCableLockStates, TeslemetryTimestamp
from .entity import (
    TeslemetryVehicleEntity,
)
from .models import TeslemetryVehicleData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry sensor platform from a config entry."""


    async_add_entities(
        klass(vehicle, Scope.VEHICLE_CMDS in entry.runtime_data.scopes)
        for klass in (
            TeslemetryVehicleLockEntity,
            TeslemetryCableLockEntity,
            TeslemetrySpeedLimitEntity,
        )
        for vehicle in entry.runtime_data.vehicles
    )

class LockRestoreEntity(LockEntity, RestoreEntity):
    """Base class for Teslemetry Lock Entities."""

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None and not self.coordinator.updated_once:
            if (state.state == "locked"):
                self._attr_is_locked = True
            elif (state.state == "unlocked"):
                self._attr_is_locked = False

class TeslemetryVehicleLockEntity(TeslemetryVehicleEntity, LockRestoreEntity):
    """Lock entity for Teslemetry."""

    def __init__(self, data: TeslemetryVehicleData, scoped: bool) -> None:
        """Initialize the sensor."""
        super().__init__(
            data,
            "vehicle_state_locked",
            TeslemetryTimestamp.VEHICLE_STATE,
            Signal.LOCKED,
        )
        self.scoped = scoped

    def _async_update_attrs(self) -> None:
        """Update entity attributes."""
        self._attr_is_locked = self._value

    def _async_value_from_stream(self, value) -> None:
        """Update entity value from stream."""
        self._attr_is_locked = value == "true"

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the doors."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.door_lock())
        self._attr_is_locked = True
        self.async_write_ha_state()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the doors."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.door_unlock())
        self._attr_is_locked = False
        self.async_write_ha_state()


class TeslemetryCableLockEntity(TeslemetryVehicleEntity, LockRestoreEntity):
    """Cable Lock entity for Teslemetry."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scoped: bool,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            data,
            "charge_state_charge_port_latch",
            TeslemetryTimestamp.CHARGE_STATE,
            Signal.CHARGE_PORT_LATCH,
        )
        self.scoped = scoped

    def _async_update_attrs(self) -> None:
        """Update entity attributes."""
        if self._value is None:
            self._attr_is_locked = None
        self._attr_is_locked = self._value == TeslemetryChargeCableLockStates.ENGAGED

    def _async_value_from_stream(self, value) -> None:
        """Update entity value from stream."""
        self._attr_is_locked = value == TeslemetryChargeCableLockStates.ENGAGED

    async def async_lock(self, **kwargs: Any) -> None:
        """Charge cable Lock cannot be manually locked."""
        raise ServiceValidationError(
            "Insert cable to lock",
            translation_domain=DOMAIN,
            translation_key="no_cable",
        )

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock charge cable lock."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.charge_port_door_open())
        self._attr_is_locked = False
        self.async_write_ha_state()


class TeslemetrySpeedLimitEntity(TeslemetryVehicleEntity, LockRestoreEntity):
    """Speed Limit with PIN entity for Tessie."""

    _attr_code_format = r"^\d\d\d\d$"

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scoped: bool,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(data, "vehicle_state_speed_limit_mode_active", TeslemetryTimestamp.VEHICLE_STATE, Signal.SPEED_LIMIT_MODE)
        self.scoped = scoped

    def _async_update_attrs(self) -> None:
        """Update entity attributes."""
        self._attr_is_locked = self._value

    async def async_lock(self, **kwargs: Any) -> None:
        """Enable speed limit with pin."""
        code: str | None = kwargs.get(ATTR_CODE)
        if code:
            self.raise_for_scope(Scope.VEHICLE_CMDS)
            await self.wake_up_if_asleep()
            await self.handle_command(self.api.speed_limit_activate(code))
            self._attr_is_locked = True
            self.async_write_ha_state()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Disable speed limit with pin."""
        code: str | None = kwargs.get(ATTR_CODE)
        if code:
            self.raise_for_scope(Scope.VEHICLE_CMDS)
            await self.wake_up_if_asleep()
            await self.handle_command(self.api.speed_limit_deactivate(code))

            self._attr_is_locked = False
            self.async_write_ha_state()
