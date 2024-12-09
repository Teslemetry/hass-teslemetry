"""Sensor platform for Teslemetry integration."""

from __future__ import annotations
from datetime import  timedelta


from homeassistant.components.sensor import (
    SensorEntity,
    RestoreSensor,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from homeassistant.util.variance import ignore_variance
from propcache import cached_property

from .const import TeslemetryState, MODELS
from .entity import (
    TeslemetryEnergyInfoEntity,
    TeslemetryEnergyLiveEntity,
    TeslemetryVehicleEntity,
    TeslemetryVehicleStreamEntity,
    TeslemetryWallConnectorEntity,
    TeslemetryEnergyHistoryEntity,
)
from .models import TeslemetryEnergyData, TeslemetryVehicleData
from .helpers import auto_type

from .sensor_descriptions import (
    TeslemetrySensorEntityDescription,
    TeslemetryTimeEntityDescription,
    TeslemetryEnergySensorEntityDescription,
    VEHICLE_DESCRIPTIONS,
    VEHICLE_TIME_DESCRIPTIONS,
    ENERGY_LIVE_DESCRIPTIONS,
    ENERGY_INFO_DESCRIPTIONS,
    ENERGY_HISTORY_DESCRIPTIONS,
    WALL_CONNECTOR_DESCRIPTIONS,
)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry sensor platform from a config entry."""

    entities = []
    for vehicle in entry.runtime_data.vehicles:
        for description in VEHICLE_DESCRIPTIONS:
            if not vehicle.api.pre2021 and description.streaming_key and description.streaming_firmware >= vehicle.firmware:
                entities.append(TeslemetryStreamSensorEntity(vehicle, description))
            elif description.polling_parent:
                entities.append(TeslemetryVehicleSensorEntity(vehicle, description))
        for description in VEHICLE_TIME_DESCRIPTIONS:
            if not vehicle.api.pre2021 and description.streaming_firmware >= vehicle.firmware:
                entities.append(TeslemetryVehicleTimeStreamSensorEntity(vehicle, description))
            else:
                entities.append(TeslemetryVehicleTimeSensorEntity(vehicle, description))

    for energysite in entry.runtime_data.energysites:
        for description in ENERGY_LIVE_DESCRIPTIONS:
            if description.key in energysite.live_coordinator.data:
                entities.append(TeslemetryEnergyLiveSensorEntity(energysite, description))
        for din in energysite.live_coordinator.data.get("wall_connectors", {}):
            for description in WALL_CONNECTOR_DESCRIPTIONS:
                entities.append(TeslemetryWallConnectorSensorEntity(energysite, din, description))
            entities.append(TeslemetryWallConnectorVehicleSensorEntity(energysite, din, entry.runtime_data.vehicles))
        for description in ENERGY_INFO_DESCRIPTIONS:
            if description.key in energysite.info_coordinator.data:
                entities.append(TeslemetryEnergyInfoSensorEntity(energysite, description))
        if energysite.history_coordinator is not None:
            for description in ENERGY_HISTORY_DESCRIPTIONS:
                entities.append(TeslemetryEnergyHistorySensorEntity(energysite, description))

    async_add_entities(entities)


class TeslemetryVehicleSensorEntity(TeslemetryVehicleEntity, SensorEntity):
    """Base class for Teslemetry vehicle metric sensors."""

    entity_description: TeslemetrySensorEntityDescription
    streaming_gap = 60000

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetrySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        assert description.polling_parent
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""

        if self.entity_description.polling_available_fn(self._value):
            self._attr_available = True
            self._attr_native_value = self.entity_description.polling_value_fn(self._value)
        else:
            self._attr_available = False
            self._attr_native_value = None

class TeslemetryStreamSensorEntity(TeslemetryVehicleStreamEntity, RestoreSensor):
    """Base class for Teslemetry vehicle streaming sensors."""

    entity_description: TeslemetrySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetrySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        assert description.streaming_key
        super().__init__(data, description.key, description.streaming_key)

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        if (sensor_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = sensor_data.native_value

    @cached_property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.stream.connected

    def _async_value_from_stream(self, value) -> None:
        """Update the value of the entity."""
        if (value is None):
            self._attr_native_value = None
        else:
            self._attr_native_value = self.entity_description.streaming_value_fn(value)

class TeslemetryVehicleTimeSensorEntity(TeslemetryVehicleEntity, SensorEntity):
    """Base class for Teslemetry vehicle metric sensors."""

    entity_description: TeslemetryTimeEntityDescription
    _last_value: int | None = None

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetryTimeEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._get_timestamp = ignore_variance(
            func=lambda value: dt_util.utcnow() + timedelta(minutes=value),
            ignored_variance=timedelta(minutes=1),
        )

        super().__init__(data, description.key)
        self._attr_translation_key = f"{self.entity_description.key}_timestamp"
        self._attr_unique_id = f"{data.vin}-{description.key}_timestamp"

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""

        value = self._value
        self._attr_available = value is not None and value > 0

        if value == self._last_value:
            # No change
            return
        self._last_value = value
        if isinstance(value, int | float):
            self._attr_native_value = self._get_timestamp(value)
        else:
            self._attr_native_value = None

class TeslemetryVehicleTimeStreamSensorEntity(TeslemetryVehicleStreamEntity, SensorEntity):
    """Base class for Teslemetry vehicle metric sensors."""

    entity_description: TeslemetryTimeEntityDescription
    _last_value: int | None = None

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: TeslemetryTimeEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._get_timestamp = ignore_variance(
            func=lambda value: dt_util.utcnow() + timedelta(minutes=value),
            ignored_variance=timedelta(minutes=1),
        )

        assert description.streaming_key
        super().__init__(data, description.key, description.streaming_key)
        self._attr_translation_key = f"{self.entity_description.key}_timestamp"
        self._attr_unique_id = f"{data.vin}-{description.key}_timestamp"

    def _async_value_from_stream(self, value) -> None:
        """Update the attributes of the sensor."""

        self._attr_available = value is not None and value > 0

        if value == self._last_value:
            # No change
            return
        self._last_value = value
        if isinstance(value, int | float):
            self._attr_native_value = self._get_timestamp(value)
        else:
            self._attr_native_value = None




class TeslemetryEnergyLiveSensorEntity(TeslemetryEnergyLiveEntity, SensorEntity):
    """Base class for Teslemetry energy site metric sensors."""

    entity_description: TeslemetryEnergySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: TeslemetryEnergySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_available = not self.exactly(None)
        self._attr_native_value = self.entity_description.value_fn(self._value)


class TeslemetryWallConnectorSensorEntity(TeslemetryWallConnectorEntity, SensorEntity):
    """Base class for Teslemetry Wall Connector sensors."""

    entity_description: TeslemetryEnergySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        din: str,
        description: TeslemetryEnergySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(
            data,
            din,
            description.key,
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""

        if not self.has:
            return

        self._attr_available = not self.exactly(None)
        self._attr_native_value = self.entity_description.value_fn(self._value)


class TeslemetryWallConnectorVehicleSensorEntity(
    TeslemetryWallConnectorEntity, SensorEntity
):
    """Entity for Teslemetry wall connector vehicle sensors."""

    entity_description: TeslemetryEnergySensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        din: str,
        vehicles: list[TeslemetryVehicleData],
    ) -> None:
        """Initialize the sensor."""
        self._vehicles = vehicles
        super().__init__(
            data,
            din,
            "vin",
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""

        if not self.has:
            return

        if self.exactly(None):
            self._attr_native_value = "None"
            self._attr_extra_state_attributes = {}
            return

        value = self._value
        for vehicle in self._vehicles:
            if vehicle.vin == value:
                self._attr_native_value = vehicle.device["name"]
                self._attr_extra_state_attributes = {
                    "vin": vehicle.vin,
                    "model": vehicle.device["model"],
                }
                return
        self._attr_native_value = value
        self._attr_extra_state_attributes = {
            "vin": value,
            "model": MODELS.get(value[3]),
        }


class TeslemetryEnergyInfoSensorEntity(TeslemetryEnergyInfoEntity, SensorEntity):
    """Base class for Teslemetry energy site metric sensors."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_available = not self.exactly(None)
        self._attr_native_value = self._value


class TeslemetryEnergyHistorySensorEntity(TeslemetryEnergyHistoryEntity, SensorEntity):
    """Base class for Teslemetry energy site metric sensors."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        data: TeslemetryEnergyData,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""

        self.entity_description = description
        super().__init__(data, description.key)

    def _async_update_attrs(self) -> None:
        """Update the attributes of the sensor."""
        self._attr_native_value = self._value


class TeslemetryVehicleEventEntity(RestoreSensor):
    """Parent class for Teslemetry Vehicle Stream entities."""

    _attr_has_entity_name = True

    def __init__(
        self, data: TeslemetryVehicleData, key: str
    ) -> None:
        """Initialize common aspects of a Teslemetry entity."""

        self.key = key
        self._attr_translation_key = f"event_{key}"
        self.stream = data.stream
        self.vin = data.vin

        self._attr_unique_id = f"{data.vin}-event_{key}"
        self._attr_device_info = data.device

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        if (sensor_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = sensor_data.native_value

        if self.stream.server:
            self.async_on_remove(
                self.stream.async_add_listener(
                    self._handle_stream_update,
                    {"vin": self.vin, self.key: None},
                )
            )

    def _handle_stream_update(self, data: dict[str, list]) -> None:
        """Handle updated data from the stream."""
        self._attr_available = self.stream.connected
        self._attr_native_value = data[self.key][0]['name']
        self.async_write_ha_state()
