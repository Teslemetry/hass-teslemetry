"""Device Tracker platform for Teslemetry integration."""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TeslemetryVehicleEntity
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
    timestamp_key = "drive_state_timestamp"
    streaming_key = None

    def __init__(
        self,
        vehicle: TeslemetryVehicleData,
    ) -> None:
        """Initialize the device tracker."""
        super().__init__(vehicle, self.key, self.timestamp_key, self.streaming_key)

    @property
    def source_type(self) -> SourceType | str:
        """Return the source type of the device tracker."""
        return SourceType.GPS


class TeslemetryDeviceTrackerLocationEntity(TeslemetryDeviceTrackerEntity):
    """Vehicle Location Device Tracker Class."""

    key = "location"
    streaming_key = "Location"

    def _async_update_attrs(self) -> None:
        """Update the attributes of the device tracker."""

        self._attr_latitude = self.get("drive_state_latitude")
        self._attr_longitude = self.get("drive_state_longitude")
        self._last_update = self.get("drive_state_timestamp")
        self._attr_available = not (
            self.exactly(None, "drive_state_longitude")
            or self.exactly(None, "drive_state_latitude")
        )


class TeslemetryDeviceTrackerRouteEntity(TeslemetryDeviceTrackerEntity):
    """Vehicle Navigation Device Tracker Class."""

    key = "route"

    def _async_update_attrs(self) -> None:
        """Update the attributes of the device tracker."""
        self._attr_latitude = self.get("drive_state_active_route_latitude")
        self._attr_longitude = self.get("drive_state_active_route_longitude")
        self._attr_location_name = self.get("drive_state_active_route_destination")
        self._attr_available = not (
            self.exactly(None, "drive_state_active_route_longitude")
            or self.exactly(None, "drive_state_active_route_latitude")
        )
