"""Cover platform for Teslemetry integration."""

from __future__ import annotations

from itertools import chain
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from tesla_fleet_api.const import Scope, SunRoofCommand, Trunk, WindowCommand
from teslemetry_stream import Signal

from .entity import (
    TeslemetryVehicleComplexStreamEntity,
    TeslemetryVehicleEntity,
    TeslemetryVehicleStreamEntity,
)
from .helpers import auto_type
from .models import TeslemetryVehicleData

CLOSED = 0
OPEN = 1

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry sensor platform from a config entry."""

    async_add_entities(
        chain(
            (
                TeslemetryPollingWindowEntity(vehicle, entry.runtime_data.scopes)
                if vehicle.api.pre2021 or vehicle.firmware < "2024.26"
                else TeslemetryStreamingWindowEntity(vehicle, entry.runtime_data.scopes)
                for vehicle in entry.runtime_data.vehicles
            ),
            (
                TeslemetryPollingChargePortEntity(vehicle, entry.runtime_data.scopes)
                if vehicle.api.pre2021 or vehicle.firmware < "2024.44.25"
                else TeslemetryStreamingChargePortEntity(vehicle, entry.runtime_data.scopes)
                for vehicle in entry.runtime_data.vehicles
            ),
            (
                TeslemetryPollingFrontTrunkEntity(vehicle, entry.runtime_data.scopes)
                if vehicle.api.pre2021 or vehicle.firmware < "2024.26"
                else TeslemetryStreamingFrontTrunkEntity(vehicle, entry.runtime_data.scopes)
                for vehicle in entry.runtime_data.vehicles
            ),
            (
                TeslemetryPollingRearTrunkEntity(vehicle, entry.runtime_data.scopes)
                if vehicle.api.pre2021 or vehicle.firmware < "2024.26"
                else TeslemetryStreamingRearTrunkEntity(vehicle, entry.runtime_data.scopes)
                for vehicle in entry.runtime_data.vehicles
            ),
            (
                TeslemetrySunroofEntity(vehicle, entry.runtime_data.scopes)
                for vehicle in entry.runtime_data.vehicles
                if vehicle.coordinator.data.get("vehicle_config_sun_roof_installed")
            )
        )
    )


class TeslemetryWindowEntity(CoverEntity):
    """Cover entity for windows."""

    _attr_device_class = CoverDeviceClass.WINDOW
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

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

class TeslemetryPollingWindowEntity(TeslemetryVehicleEntity, TeslemetryWindowEntity):
    """Polling cover entity for windows."""

    def __init__(self, data: TeslemetryVehicleData, scopes: list[Scope]) -> None:
        """Initialize the sensor."""
        super().__init__(data, "windows")
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = CoverEntityFeature(0)

    def _async_update_attrs(self) -> None:
        """Update the entity attributes."""
        fd = self.get("vehicle_state_fd_window")
        fp = self.get("vehicle_state_fp_window")
        rd = self.get("vehicle_state_rd_window")
        rp = self.get("vehicle_state_rp_window")

        if OPEN in (fd, fp, rd, rp):
            self._attr_is_closed = False
        elif None in (fd, fp, rd, rp):
            self._attr_is_closed = None
        else:
            self._attr_is_closed = True

class TeslemetryStreamingWindowEntity(TeslemetryVehicleComplexStreamEntity, TeslemetryWindowEntity, RestoreEntity):
    """Streaming cover entity for windows."""

    fd: bool | None = None
    fp: bool | None = None
    rd: bool | None = None
    rp: bool | None = None

    def __init__(self, data: TeslemetryVehicleData, scopes: list[Scope]) -> None:
        """Initialize the sensor."""
        super().__init__(data, "windows", [
            Signal.FD_WINDOW,
            Signal.FP_WINDOW,
            Signal.RD_WINDOW,
            Signal.RP_WINDOW,
        ])
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = CoverEntityFeature(0)

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            if (state.state == "open"):
                self._attr_is_closed = False
            elif (state.state == "closed"):
                self._attr_is_closed = True
            #self._attr_current_cover_position = state.attributes.get("current_cover_position")

    def _async_data_from_stream(self, data) -> None:
        """Update the entity attributes."""
        if value := data.get(Signal.FD_WINDOW):
            self.fd = value == "WindowStateOpen"
        if value := data.get(Signal.FP_WINDOW):
            self.fp = value == "WindowStateOpen"
        if value := data.get(Signal.RD_WINDOW):
            self.rd = value == "WindowStateOpen"
        if value := data.get(Signal.RP_WINDOW):
            self.rp = value == "WindowStateOpen"

        if True in (self.fd, self.fp, self.rd, self.rp):
            self._attr_is_closed = False
        elif None in (self.fd, self.fp, self.rd, self.rp):
            self._attr_is_closed = None
        else:
            self._attr_is_closed = True

class TeslemetryChargePortEntity(CoverEntity):
    """Cover entity for the charge port."""

    _attr_device_class = CoverDeviceClass.DOOR
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

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

class TeslemetryPollingChargePortEntity(TeslemetryVehicleEntity, TeslemetryChargePortEntity):
    """Polling cover entity for the charge port."""

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
        )

    def _async_update_attrs(self) -> None:
        """Update the entity attributes."""
        self._attr_is_closed = self.exactly(False)

class TeslemetryStreamingChargePortEntity(TeslemetryVehicleStreamEntity, TeslemetryChargePortEntity):
    """Streaming cover entity for the charge port."""

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
            streaming_key=Signal.CHARGE_PORT_DOOR_OPEN,
        )

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        if value is None:
            self._attr_is_closed = None
        else:
            self._attr_is_closed = not value


class TeslemetryFrontTrunkEntity(CoverEntity):
    """Cover entity for the front trunk."""

    _attr_device_class = CoverDeviceClass.DOOR
    _attr_supported_features = CoverEntityFeature.OPEN

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open front trunk."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.actuate_trunk(Trunk.FRONT))
        self._attr_is_closed = False
        self.async_write_ha_state()

    # In the future this could be extended to add aftermarket close support through a option flow

class TeslemetryPollingFrontTrunkEntity(TeslemetryVehicleEntity, TeslemetryFrontTrunkEntity):
    """Polling cover entity for the front trunk."""

    def __init__(self, vehicle: TeslemetryVehicleData, scopes: list[Scope]) -> None:
        """Initialize the sensor."""
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = CoverEntityFeature(0)
        super().__init__(vehicle, "vehicle_state_ft")

    def _async_update_attrs(self) -> None:
        """Update the entity attributes."""
        self._attr_is_closed = self.exactly(CLOSED)

class TeslemetryStreamingFrontTrunkEntity(TeslemetryVehicleStreamEntity, TeslemetryFrontTrunkEntity):
    """Streaming cover entity for the front trunk."""

    def __init__(self, vehicle: TeslemetryVehicleData, scopes: list[Scope]) -> None:
        """Initialize the sensor."""
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = CoverEntityFeature(0)
        super().__init__(vehicle, "vehicle_state_ft", Signal.DOOR_STATE)
        print(self._attr_is_closed)

    def _async_value_from_stream(self, value) -> None:
        """Update the entity attributes."""
        open = value.get("TrunkFront")

        if isinstance(open, bool):
            self._attr_is_closed = not open
        else:
            self._attr_is_closed = None
        print(self._attr_is_closed)

class TeslemetryRearTrunkEntity(CoverEntity):
    """Cover entity for the rear trunk."""

    _attr_device_class = CoverDeviceClass.DOOR
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

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


class TeslemetryPollingRearTrunkEntity(TeslemetryVehicleEntity, TeslemetryRearTrunkEntity):
    """Polling Cover entity for the rear trunk."""

    def __init__(self, vehicle: TeslemetryVehicleData, scopes: list[Scope]) -> None:
        """Initialize the sensor."""
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = CoverEntityFeature(0)
        super().__init__(vehicle, "vehicle_state_rt")

    def _async_update_attrs(self) -> None:
        """Update the entity attributes."""
        self._attr_is_closed = self.exactly(CLOSED)


class TeslemetryStreamingRearTrunkEntity(TeslemetryVehicleStreamEntity, TeslemetryRearTrunkEntity):
    """Polling Cover entity for the rear trunk."""

    def __init__(self, vehicle: TeslemetryVehicleData, scopes: list[Scope]) -> None:
        """Initialize the sensor."""
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = CoverEntityFeature(0)
        super().__init__(vehicle, "vehicle_state_rt", Signal.DOOR_STATE)

    def _async_value_from_stream(self, value) -> None:
        """Update the entity attributes."""
        value = value.get("TrunkRear")
        if value is None:
            self._attr_is_closed = None
        else:
            self._attr_is_closed = not value

class TeslemetrySunroofEntity(TeslemetryVehicleEntity, TeslemetryWindowEntity):
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
