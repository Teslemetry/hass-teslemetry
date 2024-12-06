"""Binary Sensor platform for Teslemetry integration."""

from __future__ import annotations

from itertools import chain
from collections.abc import Callable
from dataclasses import dataclass

from teslemetry_stream import TelemetryFields

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.restore_state import RestoreEntity

from .const import TeslemetryState, TeslemetryPollingKeys, TeslemetryUpdateType
from .entity import (
    TeslemetryVehicleEntity,
    TeslemetryEnergyLiveEntity,
    TeslemetryEnergyInfoEntity,
    TeslemetryVehicleStreamEntity,
)
from .models import TeslemetryVehicleData, TeslemetryEnergyData
from .helpers import auto_type

from .binary_sensor_descriptions import (
    VEHICLE_DESCRIPTIONS,
    ENERGY_LIVE_DESCRIPTIONS,
    ENERGY_INFO_DESCRIPTIONS,
)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry binary sensor platform from a config entry."""


    async_add_entities(
        chain(
            (  # Vehicle State
                TeslemetryVehicleBinarySensorStateEntity(vehicle)
                for vehicle in entry.runtime_data.vehicles
            ),
            (  # Vehicles
                TeslemetryVehicleBinarySensorEntity(vehicle, description)
                for vehicle in entry.runtime_data.vehicles
                for description in VEHICLE_DESCRIPTIONS
            ),
            (  # Energy Site Live
                TeslemetryEnergyLiveBinarySensorEntity(energysite, description)
                for energysite in entry.runtime_data.energysites
                for description in ENERGY_LIVE_DESCRIPTIONS
                if energysite.info_coordinator.data.get("components_battery")
                if description.key in energysite.live_coordinator.data
            ),
            (  # Energy Site Info
                TeslemetryEnergyInfoBinarySensorEntity(energysite, description)
                for energysite in entry.runtime_data.energysites
                for description in ENERGY_INFO_DESCRIPTIONS
                if energysite.info_coordinator.data.get("components_battery")
                if description.key in energysite.info_coordinator.data
            ),
        )
    )


class TeslemetryVehicleBinarySensorEntity(TeslemetryVehicleEntity, BinarySensorEntity, RestoreEntity):
    """Base class for Teslemetry vehicle binary sensors."""

    entity_description: TeslemetryBinarySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetryBinarySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(
            data, description.key, description.timestamp_key, description.streaming_key
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None and not self.coordinator.updated_once:
            self._attr_is_on = state.state == STATE_ON

    def _async_update_attrs(self) -> None:
        """Update the attributes of the binary sensor."""

        if self._value is None:
            self._attr_available = False
            self._attr_is_on = None
        else:
            self._attr_available = True
            self._attr_is_on = self.entity_description.is_on(self._value)

    def _async_value_from_stream(self, value) -> None:
        """Update the value from the stream."""
        self._attr_available = True
        self._attr_is_on = self.entity_description.is_on(auto_type(value))


class TeslemetryVehicleBinarySensorStateEntity(TeslemetryVehicleEntity, BinarySensorEntity, RestoreEntity):
    """Teslemetry vehicle state binary sensors."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self,
        data: TeslemetryVehicleData
    ) -> None:
        """Initialize the sensor."""
        #TeslemetryState.ONLINE
        super().__init__(data, "state")

    def _handle_stream_update(self, data) -> None:
        """Handle the data update."""
        # This is the wrong place to do this logic, move it to the init later
        if "vehicle_data" in data:
            return
        if data.get("state") is not None:
            self.coordinator.data["state"] = data["state"]
        else:
            self.coordinator.data["state"] = TeslemetryState.ONLINE
        self._updated_by = TeslemetryUpdateType.STREAMING
        self._async_update_attrs()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None and not self.coordinator.updated_once:
            self._attr_is_on = state.state == STATE_ON

        if self.stream.server:
            self.async_on_remove(
                self.stream.async_add_listener(
                    self._handle_stream_update,
                    {"vin": self.vin},
                )
            )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the binary sensor."""

        if self._value is None:
            self._attr_available = False
            self._attr_is_on = None
        else:
            self._attr_available = True
            self._attr_is_on = self._value == TeslemetryState.ONLINE



class TeslemetryStreamBinarySensorEntity(
    TeslemetryVehicleStreamEntity, BinarySensorEntity, RestoreEntity
):
    """Base class for Teslemetry vehicle streaming sensors."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            self._attr_is_on = state.state == STATE_ON

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        self._attr_is_on = self.entity_description.value_fn(auto_type(value))


class TeslemetryEnergyLiveBinarySensorEntity(
    TeslemetryEnergyLiveEntity, BinarySensorEntity
):
    """Base class for Teslemetry energy live binary sensors."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the binary sensor."""
        self._attr_is_on = self._value


class TeslemetryEnergyInfoBinarySensorEntity(
    TeslemetryEnergyInfoEntity, BinarySensorEntity
):
    """Base class for Teslemetry energy info binary sensors."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the binary sensor."""
        self._attr_is_on = self._value
