"""Lock platform for Teslemetry integration."""
from __future__ import annotations
from tesla_fleet_api.const import Scopes
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import ATTR_CODE

from .const import DOMAIN, TeslemetryChargeCableLockStates
from .entity import (
    TeslemetryVehicleEntity,
)
from .models import TeslemetryVehicleData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry sensor platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        klass(vehicle)
        for klass in (
            TeslemetryLockEntity,
            TeslemetryCableLockEntity,
            Scopes.VEHICLE_CMDS in data.scopes,
        )
        for vehicle in data.vehicles
    )


class TeslemetryLockEntity(TeslemetryVehicleEntity, LockEntity):
    """Lock entity for Teslemetry."""

    def __init__(self, vehicle: TeslemetryVehicleData, scoped: bool) -> None:
        """Initialize the sensor."""
        super().__init__(vehicle, "vehicle_state_locked")
        self.scoped = scoped

    @property
    def is_locked(self) -> bool | None:
        """Return the state of the Lock."""
        return self.get()

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the doors."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        await self.api.door_lock()
        self.set((self.key, True))

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the doors."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        await self.api.door_unlock()
        self.set((self.key, False))


class TeslemetryCableLockEntity(TeslemetryVehicleEntity, LockEntity):
    """Cable Lock entity for Teslemetry."""

    def __init__(
        self,
        vehicle: TeslemetryVehicleData,
        scoped: bool,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(vehicle, "charge_state_charge_port_latch")
        self.scoped = scoped

    @property
    def is_locked(self) -> bool | None:
        """Return the state of the Lock."""
        return self.get() == TeslemetryChargeCableLockStates.ENGAGED

    async def async_lock(self, **kwargs: Any) -> None:
        """Charge cable Lock cannot be manually locked."""
        raise ServiceValidationError(
            "Insert cable to lock",
            translation_domain=DOMAIN,
            translation_key="no_cable",
        )

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock charge cable lock."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        await self.api.charge_port_door_open()
        self.set((self.key, TeslemetryChargeCableLockStates.DISENGAGED))


class TeslemetrySpeedLimitEntity(TeslemetryVehicleEntity, LockEntity):
    """Speed Limit with PIN entity for Tessie."""

    _attr_code_format = r"^\d\d\d\d$"

    def __init__(
        self,
        vehicle: TeslemetryVehicleData,
        scoped: bool,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(vehicle, "vehicle_state_speed_limit_mode_active")
        self.scoped = scoped

    @property
    def is_locked(self) -> bool | None:
        """Return the state of the Lock."""
        return self.get()

    async def async_lock(self, **kwargs: Any) -> None:
        """Enable speed limit with pin."""
        code: str | None = kwargs.get(ATTR_CODE)
        if code:
            self.raise_for_scope()
            await self.wake_up_if_asleep()
            await self.api.speed_limit_activate(code)
            self.set((self.key, True))

    async def async_unlock(self, **kwargs: Any) -> None:
        """Disable speed limit with pin."""
        code: str | None = kwargs.get(ATTR_CODE)
        if code:
            self.raise_for_scope()
            await self.wake_up_if_asleep()
            await self.api.speed_limit_activate(code)
            self.set((self.key, False))