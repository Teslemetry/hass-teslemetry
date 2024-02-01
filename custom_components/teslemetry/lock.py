"""Lock platform for Teslemetry integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TeslemetryChargeCableLockStates
from .entity import (
    TeslemetryEnergyEntity,
    TeslemetryVehicleEntity,
    TeslemetryWallConnectorEntity,
)
from .models import TeslemetryEnergyData, TeslemetryVehicleData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry sensor platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        klass(vehicle)
        for klass in (TeslemetryLockEntity, TeslemetryCableLockEntity)
        for vehicle in data.vehicles
    )


class TeslemetryLockEntity(TeslemetryVehicleEntity, LockEntity):
    """Lock entity for Teslemetry."""

    def __init__(
        self,
        vehicle: TeslemetryVehicleData,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(vehicle, "vehicle_state_locked")

    @property
    def is_locked(self) -> bool | None:
        """Return the state of the Lock."""
        return self.get()

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the doors."""
        await self.api.door_lock()
        self.set((self.key, True))

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the doors."""
        await self.api.door_unlock()
        self.set((self.key, False))


class TeslemetryCableLockEntity(TeslemetryVehicleEntity, LockEntity):
    """Cable Lock entity for Teslemetry."""

    def __init__(
        self,
        vehicle: TeslemetryVehicleData,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(vehicle, "charge_state_charge_port_latch")

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
        await self.api.charge_port_door_open()
        self.set((self.key, TeslemetryChargeCableLockStates.DISENGAGED))
