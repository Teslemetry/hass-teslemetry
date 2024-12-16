"""Device Tracker platform for Teslemetry integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.device_tracker.config_entry import (
    TrackerEntity,
    TrackerEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_HOME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from teslemetry_stream import Signal

from .entity import TeslemetryVehicleEntity, TeslemetryVehicleStreamEntity
from .models import TeslemetryVehicleData


@dataclass(frozen=True, kw_only=True)
class TeslemetryDeviceTrackerEntityDescription(TrackerEntityDescription):
    """Describe a Teslemetry device tracker entity."""

    streaming_key: Signal
    streaming_firmware: str
    polling_prefix: str | None = None

DESCRIPTIONS: tuple[TeslemetryDeviceTrackerEntityDescription,...] = (
    TeslemetryDeviceTrackerEntityDescription(
        key="location",
        polling_prefix="drive_state",
        streaming_key=Signal.LOCATION,
        streaming_firmware="2024.26"
    ),
    TeslemetryDeviceTrackerEntityDescription(
        key="route",
        polling_prefix="drive_state_active_route",
        streaming_key=Signal.DESTINATION_LOCATION,
        streaming_firmware="2024.26"
    ),
    TeslemetryDeviceTrackerEntityDescription(
        key="origin",
        streaming_key=Signal.ORIGIN_LOCATION,
        streaming_firmware="2024.26",
        entity_registry_enabled_default=True,
    )
)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry device tracker platform from a config entry."""

    entities = []
    for vehicle in entry.runtime_data.vehicles:
        for description in DESCRIPTIONS:
            if vehicle.api.pre2021 or vehicle.firmware < description.streaming_firmware:
                if description.polling_prefix:
                    entities.append(
                        TeslemetryPollingDeviceTrackerEntity(vehicle, description)
                    )
            else:
                entities.append(
                    TeslemetryStreamingDeviceTrackerEntity(vehicle, description)
                )

    async_add_entities(entities)


class TeslemetryPollingDeviceTrackerEntity(TeslemetryVehicleEntity, TrackerEntity):
    """Base class for Teslemetry Tracker Entities."""

    entity_description = TeslemetryDeviceTrackerEntityDescription
    _attr_entity_category = None

    def __init__(
        self,
        vehicle: TeslemetryVehicleData,
        description: TeslemetryDeviceTrackerEntityDescription,
    ) -> None:
        """Initialize the device tracker."""
        super().__init__(vehicle, description.key)
        self.entity_description = description

    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""
        self._attr_latitude = self.get(f"{self.entity_description.polling_prefix}_latitude")
        self._attr_longitude = self.get(f"{self.entity_description.polling_prefix}_longitude")
        self._attr_location_name = self.get(f"{self.entity_description.polling_prefix}_destination")
        if self._attr_location_name == "Home":
            self._attr_location_name = STATE_HOME
        self._attr_available = not (
            self.exactly(None, f"{self.entity_description.polling_prefix}_longitude")
            or self.exactly(None, f"{self.entity_description.polling_prefix}_latitude")
        )

class TeslemetryStreamingDeviceTrackerEntity(TeslemetryVehicleStreamEntity, TrackerEntity):
    """Base class for Teslemetry Tracker Entities."""

    entity_description = TeslemetryDeviceTrackerEntityDescription
    _attr_entity_category = None

    def __init__(
        self,
        vehicle: TeslemetryVehicleData,
        description: TeslemetryDeviceTrackerEntityDescription,
    ) -> None:
        """Initialize the device tracker."""
        super().__init__(vehicle, description.key, description.streaming_key)
        self.entity_description = description

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        if isinstance(value, dict):
            self._attr_latitude = value["latitude"]
            self._attr_longitude = value["longitude"]
            self._attr_available = True
        self._attr_available = False
