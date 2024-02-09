"""Device Tracker platform for Teslemetry integration."""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import (
    TeslemetryVehicleEntity,
)
from .models import TeslemetryVehicleData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry device tracker platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        klass(vehicle)
        for klass in (
            TeslemetryDeviceTrackerLocationEntity,
            TeslemetryDeviceTrackerRouteEntity,
        )
        for vehicle in data.vehicles
    )


class TeslemetryDeviceTrackerEntity(TeslemetryVehicleEntity, TrackerEntity):
    """Base class for Teslemetry Tracker Entities."""

    _attr_entity_category = None

    def __init__(
        self,
        vehicle: TeslemetryVehicleData,
    ) -> None:
        """Initialize the device tracker."""
        super().__init__(vehicle, self.key)

    @property
    def source_type(self) -> SourceType | str:
        """Return the source type of the device tracker."""
        return SourceType.GPS


class TeslemetryDeviceTrackerLocationEntity(TeslemetryDeviceTrackerEntity):
    """Vehicle Location Device Tracker Class."""

    key = "location"

    @property
    def longitude(self) -> float | None:
        """Return the longitude of the device tracker."""
        return self.get("drive_state_longitude")

    @property
    def latitude(self) -> float | None:
        """Return the latitude of the device tracker."""
        return self.get("drive_state_latitude")

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return super().available and not (
            self.exactly(None, "drive_state_longitude")
            or self.exactly(None, "drive_state_latitude")
        )


class TeslemetryDeviceTrackerRouteEntity(TeslemetryDeviceTrackerEntity):
    """Vehicle Navigation Device Tracker Class."""

    key = "route"

    @property
    def longitude(self) -> float | None:
        """Return the longitude of the device tracker."""
        return self.get("drive_state_active_route_longitude")

    @property
    def latitude(self) -> float | None:
        """Return the latitude of the device tracker."""
        return self.get("drive_state_active_route_latitude")

    @property
    def location_name(self) -> str | None:
        """Return the location of the device tracker."""
        return self.get("drive_state_active_route_destination")

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return super().available and not (
            self.exactly(None, "drive_state_active_route_longitude")
            or self.exactly(None, "drive_state_active_route_latitude")
        )
