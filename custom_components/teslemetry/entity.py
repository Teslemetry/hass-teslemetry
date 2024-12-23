"""Teslemetry parent entity class."""

from typing import Any
from propcache import cached_property

from homeassistant.helpers.entity import Entity
from tesla_fleet_api import EnergySpecific, VehicleSpecific
from tesla_fleet_api.const import Scope
from teslemetry_stream import Signal

from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER

from .coordinator import (
    TeslemetryEnergySiteInfoCoordinator,
    TeslemetryEnergySiteLiveCoordinator,
    TeslemetryVehicleDataCoordinator,
    TeslemetryEnergyHistoryCoordinator
)
from .models import TeslemetryEnergyData, TeslemetryVehicleData
from .helpers import wake_up_vehicle, handle_command, handle_vehicle_command


class TeslemetryEntity(Entity):
    """Base class for all Teslemetry classes."""

    _attr_has_entity_name = True

    def raise_for_scope(self, scope: Scope):
        """Raise an error if a scope is not available."""
        if not self.scoped:
             raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="missing_scope",
                translation_placeholders={"scope": scope},
             )

    async def handle_command(self, command) -> dict[str, Any]:
        """Handle a command."""
        return await handle_command(command)

class TeslemetryVehicleStreamEntity(TeslemetryEntity):
    """Parent class for Teslemetry Vehicle Stream entities."""

    def __init__(
        self, data: TeslemetryVehicleData, key: str, streaming_key: Signal
    ) -> None:
        """Initialize common aspects of a Teslemetry entity."""
        self.streaming_key = streaming_key
        self.vehicle = data

        self.api = data.api
        self.stream = data.stream
        self.vin = data.vin
        self.add_field = data.stream.get_vehicle(self.vin).add_field

        self._attr_translation_key = key
        self._attr_unique_id = f"{data.vin}-{key}"
        self._attr_device_info = data.device

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.stream.async_add_listener(
                self._handle_stream_update,
                {"vin": self.vin, "data": {self.streaming_key: None}},
            )
        )
        self.vehicle.config_entry.async_create_background_task(
            self.hass,
            self.add_field(self.streaming_key),
            f"Adding field {self.streaming_key.value} to {self.vehicle.vin}"
        )

    def _handle_stream_update(self, data: dict[str, Any]) -> None:
        """Handle updated data from the stream."""
        try:
            self._async_value_from_stream(data["data"][self.streaming_key])
        except Exception as e:
            LOGGER.error("Error updating %s: %s", self._attr_translation_key, e)
            LOGGER.debug(data)
        self.async_write_ha_state()

    def _async_value_from_stream(self, value: Any) -> None:
        """Update the entity with the latest value from the stream."""
        raise NotImplementedError()

    async def wake_up_if_asleep(self) -> None:
        """Wake up the vehicle if its asleep."""
        await wake_up_vehicle(self.vehicle)

    @cached_property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.stream.connected and self._attr_available

class TeslemetryVehicleComplexStreamEntity(TeslemetryEntity):
    """Parent class for Teslemetry Vehicle Stream entities with multiple keys."""

    def __init__(
        self, data: TeslemetryVehicleData, key: str, streaming_keys: list[Signal]
    ) -> None:
        """Initialize common aspects of a Teslemetry entity."""
        self.streaming_keys = streaming_keys
        self.vehicle = data

        self.api = data.api
        self.stream = data.stream
        self.vin = data.vin
        self.add_field = data.stream.get_vehicle(self.vin).add_field

        self._attr_translation_key = key
        self._attr_unique_id = f"{data.vin}-{key}"
        self._attr_device_info = data.device

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.stream.async_add_listener(
                self._handle_stream_update,
                {"vin": self.vin, "data": None},
            )
        )
        for signal in self.streaming_keys:
            self.vehicle.config_entry.async_create_background_task(
                self.hass,
                self.add_field(signal),
                f"Adding field {signal.value} to {self.vehicle.vin}"
            )

    def _handle_stream_update(self, data: dict[str, Any]) -> None:
        """Handle updated data from the stream."""
        if any(key in data["data"] for key in self.streaming_keys):
            try:
                self._async_data_from_stream(data["data"])
            except Exception as e:
                LOGGER.error("Error updating %s: %s", self._attr_translation_key, e)
                LOGGER.debug(data)
            self.async_write_ha_state()

    def _async_data_from_stream(self, data: Any) -> None:
        """Update the entity with the latest value from the stream."""
        raise NotImplementedError()

    async def wake_up_if_asleep(self) -> None:
        """Wake up the vehicle if its asleep."""
        await wake_up_vehicle(self.vehicle)

    @cached_property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.stream.connected

class TeslemetryCoordinatorEntity(
    CoordinatorEntity[
        TeslemetryVehicleDataCoordinator
        | TeslemetryEnergySiteLiveCoordinator
        | TeslemetryEnergySiteInfoCoordinator
        | TeslemetryEnergyHistoryCoordinator
    ],
    TeslemetryEntity,
):
    """Parent class for all polled Teslemetry entities."""

    def __init__(
        self,
        coordinator: TeslemetryVehicleDataCoordinator
        | TeslemetryEnergySiteLiveCoordinator
        | TeslemetryEnergySiteInfoCoordinator
        | TeslemetryEnergyHistoryCoordinator,
        api: VehicleSpecific | EnergySpecific,
        key: str,
    ) -> None:
        """Initialize common aspects of a Teslemetry entity."""
        super().__init__(coordinator)
        self.api = api
        self.key = key

    @cached_property
    def available(self) -> bool:
        """Return if sensor is available."""
        return self.coordinator.last_update_success and self._attr_available

    @property
    def _value(self) -> Any | None:
        """Return a specific value from coordinator data."""
        return self.coordinator.data.get(self.key)

    def get(self, key: str, default: Any | None = None) -> Any | None:
        """Return a specific value from coordinator data."""
        return self.coordinator.data.get(key, default)

    def get_number(self, key: str, default: float) -> float:
        """Return a specific number from coordinator data."""
        if isinstance(value := self.coordinator.data.get(key), (int | float)):
            return value
        return default

    def exactly(self, value: Any, key: str | None = None) -> bool | None:
        """Return if a key exactly matches the value but retain None."""
        key = key or self.key
        if value is None:
            return self.get(key, False) is None
        current = self.get(key)
        if current is None:
            return None
        return current == value

    def has(self, key: str | None = None) -> bool:
        """Return True if a specific value is in coordinator data."""
        return (key or self.key) in self.coordinator.data


    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._async_update_attrs()
        self.async_write_ha_state()


    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""
        raise NotImplementedError()


class TeslemetryVehicleEntity(TeslemetryCoordinatorEntity):
    """Parent class for polled Teslemetry Vehicle entities."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        key: str,
    ) -> None:
        """Initialize common aspects of a Teslemetry entity."""
        self.vin = data.vin

        self.wakelock = data.wakelock
        self._attr_device_info = data.device
        self._attr_unique_id = f"{data.vin}-{key}"
        self._attr_translation_key = key

        super().__init__(data.coordinator, data.api, key)

        self._async_update_attrs()

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._async_update_attrs()
        self.async_write_ha_state()

    async def wake_up_if_asleep(self) -> None:
        """Wake up the vehicle if its asleep."""
        await wake_up_vehicle(self)

    async def handle_command(self, command) -> dict[str, Any]:
        """Handle a vehicle command."""
        return await handle_vehicle_command(command)


class TeslemetryEnergyLiveEntity(TeslemetryCoordinatorEntity):
    """Parent class for Teslemetry Energy Site Live entities."""

    def __init__(
        self,
        data: TeslemetryEnergyData,
        key: str,
    ) -> None:
        """Initialize common aspects of a Teslemetry Energy Site Live entity."""
        self._attr_unique_id = f"{data.id}-{key}"
        self._attr_device_info = data.device
        self._attr_translation_key = key

        super().__init__(data.live_coordinator, data.api, key)
        self._async_update_attrs()


class TeslemetryEnergyInfoEntity(TeslemetryCoordinatorEntity):
    """Parent class for Teslemetry Energy Site Info Entities."""

    def __init__(
        self,
        data: TeslemetryEnergyData,
        key: str,
    ) -> None:
        """Initialize common aspects of a Teslemetry Energy Site Info entity."""
        self._attr_unique_id = f"{data.id}-{key}"
        self._attr_device_info = data.device
        self._attr_translation_key = key

        super().__init__(data.info_coordinator, data.api, key)
        self._async_update_attrs()

class TeslemetryEnergyHistoryEntity(TeslemetryCoordinatorEntity):
    """Parent class for Teslemetry Energy History Entities."""

    def __init__(
        self,
        data: TeslemetryEnergyData,
        key: str,
    ) -> None:
        """Initialize common aspects of a Teslemetry Energy History entity."""
        self._attr_unique_id = f"{data.id}-{key}"
        self._attr_device_info = data.device
        self._attr_translation_key = key

        assert data.history_coordinator
        super().__init__(data.history_coordinator, data.api, key)
        self._async_update_attrs()


class TeslemetryWallConnectorEntity(
    TeslemetryCoordinatorEntity, CoordinatorEntity[TeslemetryEnergySiteLiveCoordinator]
):
    """Parent class for Teslemetry Wall Connector Entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        data: TeslemetryEnergyData,
        din: str,
        key: str,
    ) -> None:
        """Initialize common aspects of a Teslemetry entity."""
        self.din = din
        self._attr_unique_id = f"{data.id}-{din}-{key}"
        self._attr_translation_key = key

        # Find the model from the info coordinator
        model: str | None = None
        for wc in data.info_coordinator.data.get("components_wall_connectors", []):
            if wc["din"] == din:
                model = wc.get("part_name")
                break

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, din)},
            manufacturer="Tesla",
            configuration_url="https://teslemetry.com/console",
            name="Wall Connector",
            via_device=(DOMAIN, str(data.id)),
            serial_number=din.split("-")[-1],
            model=model
        )

        super().__init__(data.live_coordinator, data.api, key)
        self._async_update_attrs()

    @property
    def _value(self) -> int:
        """Return a specific wall connector value from coordinator data."""
        return (self.coordinator.data.get("wall_connectors", {})
            .get(self.din, {})
            .get(self.key)
        )

    @property
    def has(self) -> bool:
        """Return True if a specific value is in wall connector coordinator data."""
        return (self.key in self.coordinator.data
            .get("wall_connectors", {})
            .get(self.din, {})
        )
