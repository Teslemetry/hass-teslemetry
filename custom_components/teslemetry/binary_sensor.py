"""Binary Sensor platform for Teslemetry integration."""

from __future__ import annotations

from itertools import chain

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import TeslemetryState, TeslemetryUpdateType
from .entity import (
    TeslemetryVehicleEntity,
    TeslemetryEnergyLiveEntity,
    TeslemetryEnergyInfoEntity,
    TeslemetryVehicleStreamEntity,
)
from .models import TeslemetryVehicleData, TeslemetryEnergyData

from .binary_sensor_descriptions import (
    VEHICLE_DESCRIPTIONS,
    ENERGY_LIVE_DESCRIPTIONS,
    ENERGY_INFO_DESCRIPTIONS,
)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry binary sensor platform from a config entry."""

    entities = []
    for vehicle in entry.runtime_data.vehicles:
        if vehicle.api.pre2021:
            # Vehicle cannot use streaming
            for description in VEHICLE_DESCRIPTIONS:
                if description.polling_parent:
                    entities.append(TeslemetryVehicleBinarySensorEntity(vehicle, description))
        else:
            for description in VEHICLE_DESCRIPTIONS:
                if description.streaming_key and description.streaming_firmware >= vehicle.firmware:
                    entities.append(TeslemetryVehicleStreamBinarySensorEntity(vehicle, description))
                elif description.polling_parent:
                    entities.append(TeslemetryVehicleBinarySensorEntity(vehicle, description))

    for energysite in entry.runtime_data.energysites:
        for description in ENERGY_LIVE_DESCRIPTIONS:
            if description.key in energysite.live_coordinator.data:
                entities.append(TeslemetryEnergyLiveBinarySensorEntity(energysite, description))
        for description in ENERGY_INFO_DESCRIPTIONS:
            if description.key in energysite.info_coordinator.data:
                entities.append(TeslemetryEnergyInfoBinarySensorEntity(energysite, description))

    async_add_entities(entities)


class TeslemetryVehicleBinarySensorEntity(TeslemetryVehicleEntity, BinarySensorEntity):
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

    def _async_update_attrs(self) -> None:
        """Update the attributes of the binary sensor."""

        if self._value is None:
            self._attr_available = False
            self._attr_is_on = None
        else:
            self._attr_available = True
            self._attr_is_on = self.entity_description.polling_value_fn(self._value)


class TeslemetryVehicleBinarySensorStateEntity(TeslemetryVehicleEntity, BinarySensorEntity):
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



class TeslemetryVehicleStreamBinarySensorEntity(
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
        self._attr_is_on = self.entity_description.stream_value_fn(value)


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
