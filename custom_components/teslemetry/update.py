"""Update platform for Teslemetry integration."""
from __future__ import annotations

from typing import Any

from tesla_fleet_api.const import Scopes

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TeslemetryUpdateStatus
from .entity import TeslemetryVehicleEntity
from .models import TeslemetryVehicleData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry Update platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        TeslemetryUpdateEntity(vehicle, Scopes.VEHICLE_CMDS in data.scopes) for vehicle in data.vehicles
    )


class TeslemetryUpdateEntity(TeslemetryVehicleEntity, UpdateEntity):
    """Teslemetry Updates entity."""

    _attr_supported_features = UpdateEntityFeature.PROGRESS

    def __init__(
        self,
        vehicle: TeslemetryVehicleData,
        scoped: bool,
    ) -> None:
        """Initialize the Update."""
        super().__init__(vehicle, "update")
        self.scoped = scoped

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return super().available and self.has()

    @property
    def supported_features(self) -> UpdateEntityFeature:
        """Flag supported features."""
        if self.can_update and self.get("vehicle_state_software_update_status") in (
            TeslemetryUpdateStatus.AVAILABLE,
            TeslemetryUpdateStatus.SCHEDULED,
        ):
            return self._attr_supported_features | UpdateEntityFeature.INSTALL
        return self._attr_supported_features

    @property
    def installed_version(self) -> str:
        """Return the current app version."""
        # Discard build from version number
        return self.coordinator.data["vehicle_state_car_version"].split(" ")[0]

    @property
    def latest_version(self) -> str | None:
        """Return the latest version."""
        if self.get("vehicle_state_software_update_status") in (
            TeslemetryUpdateStatus.AVAILABLE,
            TeslemetryUpdateStatus.SCHEDULED,
            TeslemetryUpdateStatus.INSTALLING,
            TeslemetryUpdateStatus.DOWNLOADING,
            TeslemetryUpdateStatus.WIFI_WAIT,
        ):
            return self.get("vehicle_state_software_update_version")
        return self.installed_version

    @property
    def in_progress(self) -> bool | int | None:
        """Update installation progress."""
        if (
            self.get("vehicle_state_software_update_status")
            == TeslemetryUpdateStatus.INSTALLING
        ):
            return self.get("vehicle_state_software_update_install_perc")
        return False

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update."""
        await self.raise_for_scope()
        await self.wake_up_if_asleep()
        await self.api.schedule_software_update(0)
        self.set(
            ("vehicle_state_software_update_status", TeslemetryUpdateStatus.INSTALLING)
        )
