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


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry sensor platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        klass(vehicle, data.scopes)
        for klass in (
            TeslemetryWindowEntity,
            TeslemetryChargePortEntity,
            TeslemetryFrontTrunkEntity,
            TeslemetryRearTrunkEntity,
        )
        for vehicle in data.vehicles
    )


class TeslemetryWindowEntity(TeslemetryVehicleEntity, CoverEntity):
    """Cover entity for current charge."""

    _attr_device_class = CoverDeviceClass.WINDOW


    def __init__(self, vehicle: TeslemetryVehicleData, scopes: list[Scopes]) -> None:
        """Initialize the sensor."""
        super().__init__(vehicle, "windows")
        if Scopes.VEHICLE_CMDS in scopes:
            self._attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed or not."""
        return (
            self.get("vehicle_state_fd_window") == TeslemetryCoverStates.CLOSED
            and self.get("vehicle_state_fp_window") == TeslemetryCoverStates.CLOSED
            and self.get("vehicle_state_rd_window") == TeslemetryCoverStates.CLOSED
            and self.get("vehicle_state_rp_window") == TeslemetryCoverStates.CLOSED
        )

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open windows."""
        await self.api.window_control(command=WindowCommands.VENT)
        self.set(
            ("vehicle_state_fd_window", TeslemetryCoverStates.OPEN),
            ("vehicle_state_fp_window", TeslemetryCoverStates.OPEN),
            ("vehicle_state_rd_window", TeslemetryCoverStates.OPEN),
            ("vehicle_state_rp_window", TeslemetryCoverStates.OPEN),
        )

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close windows."""
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

    def __init__(self, vehicle: TeslemetryVehicleData, scopes: list[Scopes]) -> None:
        """Initialize the sensor."""
        super().__init__(vehicle, "charge_state_charge_port_door_open")
        if Scopes.VEHICLE_CMDS in scopes:
            self._attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed or not."""
        return not self.get()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open windows."""
        await self.api.charge_port_door_open()
        self.set((self.key, True))

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close windows."""
        await self.api.charge_port_door_close()
        self.set((self.key, False))


class TeslemetryFrontTrunkEntity(TeslemetryVehicleEntity, CoverEntity):
    """Cover entity for the charge port."""

    _attr_device_class = CoverDeviceClass.DOOR

    def __init__(self, vehicle: TeslemetryVehicleData, scopes: list[Scopes]) -> None:
        """Initialize the sensor."""
        super().__init__(vehicle, "vehicle_state_ft")
        if Scopes.VEHICLE_CMDS in scopes:
            self._attr_supported_features = CoverEntityFeature.OPEN

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed or not."""
        return self.get() == TeslemetryCoverStates.CLOSED

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open front trunk."""
        await self.api.actuate_trunk(Trunks.FRONT)
        self.set((self.key, TeslemetryCoverStates.OPEN))


class TeslemetryRearTrunkEntity(TeslemetryVehicleEntity, CoverEntity):
    """Cover entity for the charge port."""

    _attr_device_class = CoverDeviceClass.DOOR

    def __init__(self, vehicle: TeslemetryVehicleData, scopes: list[Scopes]) -> None:
        """Initialize the sensor."""
        super().__init__(vehicle, "vehicle_state_rt")
        if Scopes.VEHICLE_CMDS in scopes:
            self._attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed or not."""
        return self.get() == TeslemetryCoverStates.CLOSED

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open rear trunk."""
        if self.get() == TeslemetryCoverStates.CLOSED:
            self.api.actuate_trunk(Trunks.REAR)
            self.set((self.key, TeslemetryCoverStates.OPEN))

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close rear trunk."""
        if self.get() == TeslemetryCoverStates.OPEN:
            self.api.actuate_trunk(Trunks.REAR)
            self.set((self.key, TeslemetryCoverStates.CLOSED))
