"""Media Player platform for Teslemetry integration."""
from __future__ import annotations
from tesla_fleet_api.const import Scope

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerState,
    MediaPlayerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import (
    TeslemetryVehicleEntity,
    TeslemetryVehicleComplexStreamEntity
)
from .models import TeslemetryVehicleData


STATES = {
    "Playing": MediaPlayerState.PLAYING,
    "Paused": MediaPlayerState.PAUSED,
    "Stopped": MediaPlayerState.IDLE,
}
MAX_VOLUME = 11.0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry Media platform from a config entry."""


    async_add_entities(
        TeslemetryPollingMediaEntity(vehicle, Scope.VEHICLE_CMDS in entry.runtime_data.scopes)
        if vehicle.api.pre2021 or vehicle.firmware < "2026"
        else TeslemetryStreamingMediaEntity(vehicle, Scope.VEHICLE_CMDS in entry.runtime_data.scopes)
        for vehicle in entry.runtime_data.vehicles
    )


class TeslemetryMediaEntity(TeslemetryVehicleEntity, MediaPlayerEntity):
    """Base vehicle media player class."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_supported_features = (
        MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.VOLUME_SET
    )
    max_volume: float = MAX_VOLUME

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await self.handle_command(self.api.adjust_volume(int(volume * self.max_volume)))
        self._attr_volume_level = volume
        self.async_write_ha_state()

    async def async_media_play(self) -> None:
        """Send play command."""
        if self.state != MediaPlayerState.PLAYING:
            self.raise_for_scope(Scope.VEHICLE_CMDS)

            await self.handle_command(self.api.media_toggle_playback())
            self._attr_state = MediaPlayerState.PLAYING
            self.async_write_ha_state()

    async def async_media_pause(self) -> None:
        """Send pause command."""
        if self.state == MediaPlayerState.PLAYING:
            self.raise_for_scope(Scope.VEHICLE_CMDS)

            await self.handle_command(self.api.media_toggle_playback())
            self._attr_state = MediaPlayerState.PAUSED
            self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        """Send next track command."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await self.handle_command(self.api.media_next_track())

    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await self.handle_command(self.api.media_prev_track())

class TeslemetryPollingMediaEntity(TeslemetryVehicleEntity, MediaPlayerEntity):
    """Polling vehicle media player class."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scoped: bool,
    ) -> None:
        """Initialize the media player entity."""
        super().__init__(data, "media")
        self.scoped = scoped
        if not scoped:
            self._attr_supported_features = MediaPlayerEntityFeature(0)

    def _async_update_attrs(self) -> None:
        """Update entity attributes."""
        self.max_volume = self.get("vehicle_state_media_info_audio_volume_max", MAX_VOLUME)
        self._attr_state = STATES.get(
            self.get("vehicle_state_media_info_media_playback_status"),
            MediaPlayerState.OFF,
        )
        self._attr_volume_step = (
            1.0
            / self.max_volume
            / self.get("vehicle_state_media_info_audio_volume_increment", 1.0 / 3)
        )
        self._attr_volume_level = (
            self.get("vehicle_state_media_info_audio_volume", 0) / self.max_volume
        )

        if duration := self.get("vehicle_state_media_info_now_playing_duration"):
            self._attr_media_duration = duration / 1000
        else:
            self._attr_media_duration = None

        if duration:  # Return media position only when a media duration is > 0
            self._attr_media_position = (
                self.get("vehicle_state_media_info_now_playing_elapsed") / 1000
            )
        else:
            self._attr_media_position = None

        self._attr_media_title = self.get("vehicle_state_media_info_now_playing_title")
        self._attr_media_artist = self.get(
            "vehicle_state_media_info_now_playing_artist"
        )
        self._attr_media_album_name = self.get(
            "vehicle_state_media_info_now_playing_album"
        )
        self._attr_media_playlist = self.get(
            "vehicle_state_media_info_now_playing_station"
        )
        self._attr_source = self.get("vehicle_state_media_info_now_playing_source")

class TeslemetryStreamingMediaEntity(TeslemetryVehicleComplexStreamEntity, MediaPlayerEntity):
    """Streaming vehicle media player class."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scoped: bool,
    ) -> None:
        """Initialize the media player entity."""
        super().__init__(data, "media", [])
        self.scoped = scoped
        if not scoped:
            self._attr_supported_features = MediaPlayerEntityFeature(0)

    def _async_update_attrs(self) -> None:
        """Update entity attributes."""
        pass
        # NOT IMPLEMENTED BY TESLA YET
