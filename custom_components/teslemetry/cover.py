"""Cover platform for Teslemetry integration."""

from __future__ import annotations

from typing import Any

from tesla_fleet_api.const import WindowCommand, Trunk, Scope, SunRoofCommand
from teslemetry_stream import TelemetryFields

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import TeslemetryCoverStates, TeslemetryTimestamp
from .entity import TeslemetryVehicleEntity
from .models import TeslemetryVehicleData
from .helpers import auto_type

CLOSED = 0
OPEN = 1

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry sensor platform from a config entry."""


    async_add_entities(
        klass(vehicle, entry.runtime_data.scopes)
        for (klass) in (
            TeslemetryWindowEntity,
            TeslemetryChargePortEntity,
            TeslemetryFrontTrunkEntity,
            TeslemetryRearTrunkEntity,
            TeslemetrySunroofEntity,
        )
        for vehicle in entry.runtime_data.vehicles
    )


class CoverRestoreEntity(CoverEntity, RestoreEntity):
    """Base class for cover entities that need to restore state."""

    _attr_is_closed: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None and not self.coordinator.updated_once:
            if (state.state == "open"):
                self._attr_is_closed = False
            elif (state.state == "closed"):
                self._attr_is_closed = True
            self._attr_current_cover_position = state.attributes.get("current_cover_position")


class TeslemetryWindowEntity(TeslemetryVehicleEntity, CoverRestoreEntity):
    """Cover entity for windows."""

    _attr_device_class = CoverDeviceClass.WINDOW
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(self, data: TeslemetryVehicleData, scopes: list[Scope]) -> None:
        """Initialize the sensor."""
        super().__init__(
            data, "windows", timestamp_key=TeslemetryTimestamp.VEHICLE_STATE
        )
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = CoverEntityFeature(0)

    def _async_update_attrs(self) -> None:
        """Update the entity attributes."""
        fd = self.get("vehicle_state_fd_window")
        fp = self.get("vehicle_state_fp_window")
        rd = self.get("vehicle_state_rd_window")
        rp = self.get("vehicle_state_rp_window")

        # Any open set to open
        if OPEN in (fd, fp, rd, rp):
            self._attr_is_closed = False
        # All closed set to closed
        elif CLOSED == fd == fp == rd == rp:
            self._attr_is_closed = True
        # Otherwise, set to unknown
        else:
            self._attr_is_closed = None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Vent windows."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.window_control(command=WindowCommand.VENT))
        self._attr_is_closed = False
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close windows."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.window_control(command=WindowCommand.CLOSE))
        self._attr_is_closed = True
        self.async_write_ha_state()


class TeslemetryChargePortEntity(TeslemetryVehicleEntity, CoverRestoreEntity):
    """Cover entity for the charge port."""

    _attr_device_class = CoverDeviceClass.DOOR
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(self, vehicle: TeslemetryVehicleData, scopes: list[Scope]) -> None:
        """Initialize the sensor."""
        self.scoped = any(
            scope in scopes
            for scope in [Scope.VEHICLE_CMDS, Scope.VEHICLE_CHARGING_CMDS]
        )
        if not self.scoped:
            self._attr_supported_features = CoverEntityFeature(0)

        super().__init__(
            vehicle,
            "charge_state_charge_port_door_open",
            timestamp_key=TeslemetryTimestamp.CHARGE_STATE,
            streaming_key=TelemetryFields.CHARGE_PORT,
        )

    def _async_update_attrs(self) -> None:
        """Update the entity attributes."""
        self._attr_is_closed = not self._value

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        self._attr_is_closed = not auto_type(value)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open windows."""
        self.raise_for_scope(Scope.VEHICLE_CHARGING_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.charge_port_door_open())
        self._attr_is_closed = False
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close windows."""
        self.raise_for_scope(Scope.VEHICLE_CHARGING_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.charge_port_door_close())
        self._attr_is_closed = True
        self.async_write_ha_state()


class TeslemetryFrontTrunkEntity(TeslemetryVehicleEntity, CoverRestoreEntity):
    """Cover entity for the front trunk."""

    _attr_device_class = CoverDeviceClass.DOOR
    _attr_supported_features = CoverEntityFeature.OPEN

    def __init__(self, vehicle: TeslemetryVehicleData, scopes: list[Scope]) -> None:
        """Initialize the sensor."""
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = CoverEntityFeature(0)
        super().__init__(vehicle, "vehicle_state_ft")

    def _async_update_attrs(self) -> None:
        """Update the entity attributes."""
        self._attr_is_closed = self.exactly(CLOSED)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open front trunk."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.actuate_trunk(Trunk.FRONT))
        self._attr_is_closed = False
        self.async_write_ha_state()

    # In the future this could be extended to add aftermarket close support through a option flow


class TeslemetryRearTrunkEntity(TeslemetryVehicleEntity, CoverRestoreEntity):
    """Cover entity for the rear trunk."""

    _attr_device_class = CoverDeviceClass.DOOR
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(self, vehicle: TeslemetryVehicleData, scopes: list[Scope]) -> None:
        """Initialize the sensor."""
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = CoverEntityFeature(0)
        super().__init__(vehicle, "vehicle_state_rt")

    def _async_update_attrs(self) -> None:
        """Update the entity attributes."""
        self._attr_is_closed = self.exactly(CLOSED)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open rear trunk."""
        if self.is_closed is not False:
            self.raise_for_scope(Scope.VEHICLE_CMDS)
            await self.wake_up_if_asleep()
            await self.handle_command(self.api.actuate_trunk(Trunk.REAR))
            self._attr_is_closed = False
            self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close rear trunk."""
        if self.is_closed is not True:
            self.raise_for_scope(Scope.VEHICLE_CMDS)
            await self.wake_up_if_asleep()
            await self.handle_command(self.api.actuate_trunk(Trunk.REAR))
            self._attr_is_closed = True
            self.async_write_ha_state()

class TeslemetrySunroofEntity(TeslemetryVehicleEntity, CoverRestoreEntity):
    """Cover entity for the sunroof."""

    _attr_device_class = CoverDeviceClass.WINDOW
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    _attr_entity_registry_enabled_default = False

    def __init__(self, vehicle: TeslemetryVehicleData, scopes: list[Scope]) -> None:
        """Initialize the sensor."""
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = CoverEntityFeature(0)
        super().__init__(vehicle, "vehicle_state_sun_roof_state")

    def _async_update_attrs(self) -> None:
        """Update the entity attributes."""
        value = self._value
        if value == None or value == "unknown":
            self._attr_is_closed = None
        else:
            self._attr_is_closed = value == "closed"

        self._attr_current_cover_position = self.get("vehicle_state_sun_roof_percent_open")

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open sunroof."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.sun_roof_control(SunRoofCommand.VENT))
        self._attr_is_closed = False
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close sunroof."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.sun_roof_control(SunRoofCommand.CLOSE))
        self._attr_is_closed = True
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Close sunroof."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.sun_roof_control(SunRoofCommand.STOP))
        self._attr_is_closed = False
        self.async_write_ha_state()
