"""Cover platform for Teslemetry integration."""
from __future__ import annotations

from typing import Any

from tesla_fleet_api.const import WindowCommands, Trunks, Scopes

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TeslemetryCoverStates
from .entity import TeslemetryVehicleEntity
from .models import TeslemetryVehicleData
from .context import handle_command

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry sensor platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        klass(vehicle, any(scope in data.scopes for scope in scopes))
        for (klass, scopes) in (
            (TeslemetryWindowEntity, [Scopes.VEHICLE_CMDS]),
            (
                TeslemetryChargePortEntity,
                [Scopes.VEHICLE_CMDS, Scopes.VEHICLE_CHARGING_CMDS],
            ),
            (TeslemetryFrontTrunkEntity, [Scopes.VEHICLE_CMDS]),
            (TeslemetryRearTrunkEntity, [Scopes.VEHICLE_CMDS]),
        )
        for vehicle in data.vehicles
    )


class TeslemetryWindowEntity(TeslemetryVehicleEntity, CoverEntity):
    """Cover entity for current charge."""

    _attr_device_class = CoverDeviceClass.WINDOW
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(self, data: TeslemetryVehicleData, scoped) -> None:
        """Initialize the sensor."""
        super().__init__(data, "windows")
        self.scoped = scoped
        if not scoped:
            self._attr_supported_features = CoverEntityFeature(0)

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed or not."""
        fd = self.get("vehicle_state_fd_window")
        fp = self.get("vehicle_state_fp_window")
        rd = self.get("vehicle_state_rd_window")
        rp = self.get("vehicle_state_rp_window")

        if fd or fp or rd or rp == TeslemetryCoverStates.OPEN:
            return False
        if fd and fp and rd and rp == TeslemetryCoverStates.CLOSED:
            return True
        return None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Vent windows."""
        self.raise_for_scope()
        with handle_command():
            await self.wake_up_if_asleep()
            await self.api.window_control(command=WindowCommands.VENT)
        self.set(
            ("vehicle_state_fd_window", TeslemetryCoverStates.OPEN),
            ("vehicle_state_fp_window", TeslemetryCoverStates.OPEN),
            ("vehicle_state_rd_window", TeslemetryCoverStates.OPEN),
            ("vehicle_state_rp_window", TeslemetryCoverStates.OPEN),
        )

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close windows."""
        self.raise_for_scope()
        with handle_command():
            await self.wake_up_if_asleep()
            await self.api.window_control(command=WindowCommands.CLOSE)
        self.set(
            ("vehicle_state_fd_window", TeslemetryCoverStates.CLOSED),
            ("vehicle_state_fp_window", TeslemetryCoverStates.CLOSED),
            ("vehicle_state_rd_window", TeslemetryCoverStates.CLOSED),
            ("vehicle_state_rp_window", TeslemetryCoverStates.CLOSED),
        )


class TeslemetryChargePortEntity(TeslemetryVehicleEntity, CoverEntity):
    """Cover entity for the charge port."""

    _attr_device_class = CoverDeviceClass.DOOR
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(self, vehicle: TeslemetryVehicleData, scoped) -> None:
        """Initialize the sensor."""
        super().__init__(vehicle, "charge_state_charge_port_door_open")
        self.scoped = scoped
        if not scoped:
            self._attr_supported_features = CoverEntityFeature(0)

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed or not."""
        return not self.get()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open windows."""
        self.raise_for_scope()
        with handle_command():
            await self.wake_up_if_asleep()
            await self.api.charge_port_door_open()
        self.set((self.key, True))

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close windows."""
        self.raise_for_scope()
        with handle_command():
            await self.wake_up_if_asleep()
            await self.api.charge_port_door_close()
        self.set((self.key, False))


class TeslemetryFrontTrunkEntity(TeslemetryVehicleEntity, CoverEntity):
    """Cover entity for the charge port."""

    _attr_device_class = CoverDeviceClass.DOOR
    _attr_supported_features = CoverEntityFeature.OPEN

    def __init__(self, vehicle: TeslemetryVehicleData, scoped) -> None:
        """Initialize the sensor."""
        super().__init__(vehicle, "vehicle_state_ft")

        self.scoped = scoped
        if not scoped:
            self._attr_supported_features = CoverEntityFeature(0)

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed or not."""
        return self.exactly(TeslemetryCoverStates.CLOSED)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open front trunk."""
        self.raise_for_scope()
        with handle_command():
            await self.wake_up_if_asleep()
            await self.api.actuate_trunk("front")
        self.set((self.key, TeslemetryCoverStates.OPEN))


class TeslemetryRearTrunkEntity(TeslemetryVehicleEntity, CoverEntity):
    """Cover entity for the charge port."""

    _attr_device_class = CoverDeviceClass.DOOR
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(self, vehicle: TeslemetryVehicleData, scoped) -> None:
        """Initialize the sensor."""
        super().__init__(vehicle, "vehicle_state_rt")
        self.scoped = scoped
        if not scoped:
            self._attr_supported_features = CoverEntityFeature(0)

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed or not."""
        value = self.get()
        if value == TeslemetryCoverStates.CLOSED:
            return True
        if value == TeslemetryCoverStates.OPEN:
            return False
        return None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open rear trunk."""
        if self.get() == TeslemetryCoverStates.CLOSED:
            self.raise_for_scope()
            with handle_command():
                await self.wake_up_if_asleep()
                self.api.actuate_trunk("rear")
            self.set((self.key, TeslemetryCoverStates.OPEN))

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close rear trunk."""
        if self.get() == TeslemetryCoverStates.OPEN:
            self.raise_for_scope()
            with handle_command():
                await self.wake_up_if_asleep()
                self.api.actuate_trunk("rear")
            self.set((self.key, TeslemetryCoverStates.CLOSED))
