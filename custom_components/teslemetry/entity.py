"""Teslemetry parent entity class."""

from typing import Any
from time import time

from tesla_fleet_api import EnergySpecific, VehicleSpecific
from tesla_fleet_api.const import TelemetryField, Scope

from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    TeslemetryTimestamp,
    TeslemetryUpdateType,
)
from .coordinator import (
    TeslemetryEnergySiteInfoCoordinator,
    TeslemetryEnergySiteLiveCoordinator,
    TeslemetryVehicleDataCoordinator,
    TeslemetryEnergyHistoryCoordinator
)
from .models import TeslemetryEnergyData, TeslemetryVehicleData
from .helpers import wake_up_vehicle, handle_command, handle_vehicle_command


class TeslemetryVehicleStreamEntity:
    """Parent class for Teslemetry Vehicle Stream entities."""

    _attr_has_entity_name = True

    def __init__(
        self, data: TeslemetryVehicleData, streaming_key: TelemetryField
    ) -> None:
        """Initialize common aspects of a Teslemetry entity."""
        self.streaming_key = streaming_key

        self._attr_translation_key = f"stream_{streaming_key.lower()}"
        self.stream = data.stream
        self.vin = data.vin
        self.fields = data.fields

        self._attr_unique_id = f"{data.vin}-stream_{streaming_key.lower()}"
        self._attr_device_info = data.device

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        if self.stream.server:
            self.async_on_remove(
                self.stream.async_add_listener(
                    self._handle_stream_update,
                    {"vin": self.vin, "data": {self.streaming_key: None}},
                )
            )
            self.hass.async_create_task(self.fields.add(self.streaming_key))

    def _handle_stream_update(self, data: dict[str, Any]) -> None:
        """Handle updated data from the stream."""
        self._async_value_from_stream(data["data"][self.streaming_key])
        self.async_write_ha_state()


class TeslemetryVehicleComplexStreamEntity:
    """Parent class for Teslemetry Vehicle Stream entities with multiple keys."""

    _attr_has_entity_name = True

    def __init__(
        self, data: TeslemetryVehicleData, key: str, streaming_keys: [TelemetryField]
    ) -> None:
        """Initialize common aspects of a Teslemetry entity."""
        self.streaming_keys = streaming_keys

        self._attr_translation_key = key
        self.stream = data.stream
        self.vin = data.vin

        self._attr_unique_id = f"{data.vin}-{key}"
        self._attr_device_info = data.device

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        if self.stream.server:
            self.async_on_remove(
                self.stream.async_add_listener(
                    self._handle_stream_update,
                    {"vin": self.vin, "data": ({key: None} for key in self.streaming_keys)},
                )
            )

    def _handle_stream_update(self, data: dict[str, Any]) -> None:
        """Handle updated data from the stream."""
        self._async_value_from_stream(data["data"])
        self.async_write_ha_state()

class TeslemetryEntity(
    CoordinatorEntity[
        TeslemetryVehicleDataCoordinator
        | TeslemetryEnergySiteLiveCoordinator
        | TeslemetryEnergySiteInfoCoordinator
        | TeslemetryEnergyHistoryCoordinator
    ]
):
    """Parent class for all Teslemetry entities."""

    _attr_has_entity_name = True

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
        self._attr_translation_key = self.key

    @property
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
        if isinstance(value := self.coordinator.data.get(key), (int, float)):
            return value
        return default

    def exactly(self, value: Any, key: str | None = None) -> bool | None:
        """Return if a key exactly matches the valug but retain None."""
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

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._async_update_attrs()
        self.async_write_ha_state()


    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""
        raise NotImplementedError()


class TeslemetryVehicleEntity(TeslemetryEntity):
    """Parent class for Teslemetry Vehicle entities."""

    _updated_at: int = 0
    _updated_by: TeslemetryUpdateType = TeslemetryUpdateType.NONE
    streaming_gap: int = 0

    def __init__(
        self,
        data: TeslemetryVehicleData,
        key: str,
        timestamp_key: TeslemetryTimestamp | None = None,
        streaming_key: TelemetryField | None = None,
    ) -> None:
        """Initialize common aspects of a Teslemetry entity."""
        self.timestamp_key = timestamp_key
        self.streaming_key = streaming_key
        self.stream = data.stream
        self.vin = data.vin

        self._attr_unique_id = f"{data.vin}-{key}"
        self.wakelock = data.wakelock

        self._attr_device_info = data.device

        super().__init__(data.coordinator, data.api, key)

        if self.coordinator.updated_once or self.key == "state":
            self._async_update_attrs()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        if self.stream.server and self.streaming_key:
            self.async_on_remove(
                self.stream.async_add_listener(
                    self._handle_stream_update,
                    {"vin": self.vin, "data": {self.streaming_key: None}},
                )
            )

    def _handle_stream_update(self, data: dict[str, Any]) -> None:
        """Handle updated data from the stream."""
        self._updated_by = TeslemetryUpdateType.STREAMING
        self._updated_at = data["timestamp"]
        self._async_value_from_stream(data["data"][self.streaming_key])
        self._attr_extra_state_attributes = {
            "updated_by": self._updated_by.value,
            "updated_at": dt_util.utc_from_timestamp(self._updated_at / 1000),
        }
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        timestamp = (
            self.timestamp_key and self.get(self.timestamp_key) or int(time() * 1000)
        )
        if (
            self._updated_by != TeslemetryUpdateType.STREAMING
            and timestamp > self._updated_at
            or timestamp > (self._updated_at + self.streaming_gap)
        ):
            self._updated_by = TeslemetryUpdateType.POLLING
            self._updated_at = timestamp

            if self.coordinator.updated_once or self.key == "state":
                self._async_update_attrs()

            self._attr_extra_state_attributes = {
                "updated_by": self._updated_by.value,
                "updated_at": dt_util.utc_from_timestamp(self._updated_at / 1000),
            }
            self.async_write_ha_state()


    async def wake_up_if_asleep(self) -> None:
        """Wake up the vehicle if its asleep."""
        await wake_up_vehicle(self)

    async def handle_command(self, command) -> dict[str, Any]:
        """Handle a vehicle command."""
        return await handle_vehicle_command(command)


class TeslemetryEnergyLiveEntity(TeslemetryEntity):
    """Parent class for Teslemetry Energy Site Live entities."""

    def __init__(
        self,
        data: TeslemetryEnergyData,
        key: str,
    ) -> None:
        """Initialize common aspects of a Teslemetry Energy Site Live entity."""
        self._attr_unique_id = f"{data.id}-{key}"
        self._attr_device_info = data.device

        super().__init__(data.live_coordinator, data.api, key)
        self._async_update_attrs()


class TeslemetryEnergyInfoEntity(TeslemetryEntity):
    """Parent class for Teslemetry Energy Site Info Entities."""

    def __init__(
        self,
        data: TeslemetryEnergyData,
        key: str,
    ) -> None:
        """Initialize common aspects of a Teslemetry Energy Site Info entity."""
        self._attr_unique_id = f"{data.id}-{key}"
        self._attr_device_info = data.device

        super().__init__(data.info_coordinator, data.api, key)
        self._async_update_attrs()

class TeslemetryEnergyHistoryEntity(TeslemetryEntity):
    """Parent class for Teslemetry Energy History Entities."""

    def __init__(
        self,
        data: TeslemetryEnergyData,
        key: str,
    ) -> None:
        """Initialize common aspects of a Teslemetry Energy History entity."""
        self._attr_unique_id = f"{data.id}-{key}"
        self._attr_device_info = data.device

        super().__init__(data.history_coordinator, data.api, key)
        self._async_update_attrs()


class TeslemetryWallConnectorEntity(
    TeslemetryEntity, CoordinatorEntity[TeslemetryEnergySiteLiveCoordinator]
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
