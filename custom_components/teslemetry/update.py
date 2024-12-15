"""Update platform for Teslemetry integration."""

from __future__ import annotations

from typing import Any

from tesla_fleet_api.const import Scope
from teslemetry_stream import Signal

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import TeslemetryUpdateStatus
from .entity import TeslemetryVehicleEntity, TeslemetryVehicleComplexStreamEntity
from .models import TeslemetryVehicleData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry Update platform from a config entry."""


    async_add_entities(
        TeslemetryPollingUpdateEntity(vehicle, Scope.VEHICLE_CMDS in entry.runtime_data.scopes)
        if vehicle.api.pre2021 or vehicle.firmware < "2024.44.25"
        else TeslemetryStreamingUpdateEntity(vehicle, Scope.VEHICLE_CMDS in entry.runtime_data.scopes)
        for vehicle in entry.runtime_data.vehicles
    )


class TeslemetryUpdateEntity(UpdateEntity):
    """Teslemetry Updates entity."""

    _attr_supported_features = UpdateEntityFeature.PROGRESS

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.schedule_software_update(offset_sec=60))
        self._attr_state = TeslemetryUpdateStatus.INSTALLING
        self.async_write_ha_state()

class TeslemetryPollingUpdateEntity(TeslemetryVehicleEntity, TeslemetryUpdateEntity):
    """Teslemetry Updates entity."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scoped: bool,
    ) -> None:
        """Initialize the Update."""
        self.scoped = scoped
        super().__init__(
            data,
            "vehicle_state_software_update_status",
        )

    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""

        # Supported Features
        if self.scoped and self._value in (
            TeslemetryUpdateStatus.AVAILABLE,
            TeslemetryUpdateStatus.SCHEDULED,
        ):
            self._attr_supported_features = (
                UpdateEntityFeature.PROGRESS | UpdateEntityFeature.INSTALL
            )
        else:
            self._attr_supported_features = UpdateEntityFeature.PROGRESS

        # Installed Version
        self._attr_installed_version = self.get("vehicle_state_car_version")
        if self._attr_installed_version is not None:
            # Remove build from version
            self._attr_installed_version = self._attr_installed_version.split(" ")[0]

        # Latest Version
        if self._value in (
            TeslemetryUpdateStatus.AVAILABLE,
            TeslemetryUpdateStatus.SCHEDULED,
            TeslemetryUpdateStatus.INSTALLING,
            TeslemetryUpdateStatus.DOWNLOADING,
            TeslemetryUpdateStatus.WIFI_WAIT,
        ):
            self._attr_latest_version = self.coordinator.data[
                "vehicle_state_software_update_version"
            ]
        else:
            self._attr_latest_version = self._attr_installed_version

        # In Progress
        if self._value in (
            TeslemetryUpdateStatus.SCHEDULED,
            TeslemetryUpdateStatus.INSTALLING,
        ):
            self._attr_in_progress = self.get(
                "vehicle_state_software_update_install_perc"
            )
        else:
            self._attr_in_progress = False


class TeslemetryStreamingUpdateEntity(TeslemetryVehicleComplexStreamEntity, TeslemetryUpdateEntity):
    """Teslemetry Updates entity."""

    _download_percentage: int = 0
    _install_percentage: int = 0

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scoped: bool,
    ) -> None:
        """Initialize the Update."""
        self.scoped = scoped
        super().__init__(
            data,
            "vehicle_state_software_update_status",
            [
                Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE,
                Signal.SOFTWARE_UPDATE_EXPECTED_DURATION_MINUTES,
                Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE,
                Signal.SOFTWARE_UPDATE_SCHEDULED_START_TIME,
                Signal.SOFTWARE_UPDATE_VERSION,
                Signal.VERSION
            ]
        )

    def _async_data_from_stream(self, data) -> None:
        """Update the attributes of the entity."""

        if Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE in data:
            self._download_percentage = data[Signal.SOFTWARE_UPDATE_DOWNLOAD_PERCENT_COMPLETE]
        if Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE in data:
            self._install_percentage = data[Signal.SOFTWARE_UPDATE_INSTALLATION_PERCENT_COMPLETE]
        if Signal.VERSION in data:
            self._installed_version = data[Signal.SOFTWARE_UPDATE_VERSION].split(" ")[0]
        if Signal.SOFTWARE_UPDATE_VERSION in data:
            self._attr_latest_version = data[Signal.SOFTWARE_UPDATE_VERSION]


        # Supported Features
        if self.scoped and self._download_percentage == 100:
            self._attr_supported_features = (
                UpdateEntityFeature.PROGRESS | UpdateEntityFeature.INSTALL
            )
        else:
            self._attr_supported_features = UpdateEntityFeature.PROGRESS


        # In Progress
        if self._download_percentage > 0:
            self._attr_in_progress = self._download_percentage
        elif self._install_percentage > 0:
            self._attr_in_progress = self._install_percentage
        else:
            self._attr_in_progress = False
