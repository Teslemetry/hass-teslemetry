"""Media Player platform for Teslemetry integration."""
from __future__ import annotations
from homeassistant.helpers.restore_state import RestoreEntity
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
from tesla_fleet_api.teslemetry.vehicles import VehicleFleet

from custom_components.teslemetry.helpers import handle_vehicle_command

from .entity import (
    TeslemetryRootEntity,
    TeslemetryVehicleEntity,
    TeslemetryVehicleStreamEntity
)
from .models import TeslemetryVehicleData


STATES = {
    "Playing": MediaPlayerState.PLAYING,
    "Paused": MediaPlayerState.PAUSED,
    "Stopped": MediaPlayerState.IDLE,
}
DISPLAY_STATES = {
    "On": MediaPlayerState.IDLE,
    "Accessory": MediaPlayerState.IDLE,
    "Charging": MediaPlayerState.OFF,
    "Sentry": MediaPlayerState.OFF,
    "Off": MediaPlayerState.OFF,
}
# Tesla uses 31 steps, in 0.333 increments up to 10.333
VOLUME_STEP = 1 / 31
VOLUME_FACTOR = 31 / 3 # 10.333



async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry Media platform from a config entry."""


    async_add_entities(
        TeslemetryPollingMediaEntity(vehicle, entry.runtime_data.scopes)
        if vehicle.api.pre2021 or vehicle.firmware < "2025.2.6"
        else TeslemetryStreamingMediaEntity(vehicle, entry.runtime_data.scopes)
        for vehicle in entry.runtime_data.vehicles
    )


class TeslemetryMediaEntity(TeslemetryRootEntity, MediaPlayerEntity):
    """Base vehicle media player class."""

    api: VehicleFleet

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_volume_step = VOLUME_STEP

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await handle_vehicle_command(self.api.adjust_volume(volume*VOLUME_FACTOR))
        self._attr_volume_level = volume
        self.async_write_ha_state()

    async def async_media_play(self) -> None:
        """Send play command."""
        if self.state != MediaPlayerState.PLAYING:
            self.raise_for_scope(Scope.VEHICLE_CMDS)

            await handle_vehicle_command(self.api.media_toggle_playback())
            self._attr_state = MediaPlayerState.PLAYING
            self.async_write_ha_state()

    async def async_media_pause(self) -> None:
        """Send pause command."""

        if self.state == MediaPlayerState.PLAYING:
            self.raise_for_scope(Scope.VEHICLE_CMDS)

            await handle_vehicle_command(self.api.media_toggle_playback())
            self._attr_state = MediaPlayerState.PAUSED
            self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        """Send next track command."""

        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await handle_vehicle_command(self.api.media_next_track())

    async def async_media_previous_track(self) -> None:
        """Send previous track command."""

        self.raise_for_scope(Scope.VEHICLE_CMDS)
        await handle_vehicle_command(self.api.media_prev_track())

class TeslemetryPollingMediaEntity(TeslemetryVehicleEntity, TeslemetryMediaEntity):
    """Polling vehicle media player class."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the media player entity."""
        super().__init__(data, "media")

        self._attr_supported_features = (
            MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.VOLUME_SET
        )
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not scoped:
            self._attr_supported_features = MediaPlayerEntityFeature(0)

    def _async_update_attrs(self) -> None:
        """Update entity attributes."""
        state = self.get("vehicle_state_media_info_media_playback_status")
        self._attr_state = STATES[state] if state in STATES else None
        self._attr_volume_level = (
            self.get("vehicle_state_media_info_audio_volume", 0) / VOLUME_FACTOR
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

class TeslemetryStreamingMediaEntity(TeslemetryVehicleStreamEntity, TeslemetryMediaEntity, RestoreEntity):
    """Streaming vehicle media player class."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the media player entity."""
        super().__init__(data, "media")

        self._attr_supported_features = (
            MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.VOLUME_SET
        )
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = MediaPlayerEntityFeature(0)


    async def async_added_to_hass(self) -> None:
        """Call when entity is added to hass."""

        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            self._attr_state = None if state.state == "Unknown" else MediaPlayerState(state.state)
            self._attr_volume_level = state.attributes.get("volume_level")
            self._attr_media_title = state.attributes.get("media_title")
            self._attr_media_artist = state.attributes.get("media_artist")
            self._attr_media_album_name = state.attributes.get("media_album_name")
            self._attr_media_playlist = state.attributes.get("media_playlist")
            self._attr_source = state.attributes.get("source")

            self.async_write_ha_state()

        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_CenterDisplay(
                self._async_handle_center_display
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_MediaPlaybackStatus(
                self._async_handle_media_playback_status
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_MediaPlaybackSource(
                self._async_handle_media_playback_source
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_MediaAudioVolume(
                self._async_handle_media_audio_volume
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_MediaNowPlayingDuration(
                self._async_handle_media_now_playing_duration
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_MediaNowPlayingElapsed(
                self._async_handle_media_now_playing_elapsed
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_MediaNowPlayingArtist(
                self._async_handle_media_now_playing_artist
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_MediaNowPlayingAlbum(
                self._async_handle_media_now_playing_album
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_MediaNowPlayingTitle(
                self._async_handle_media_now_playing_title
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_MediaNowPlayingStation(
                self._async_handle_media_now_playing_station
            )
        )

    def _async_handle_center_display(self, value: str | None) -> None:
        """Update entity attributes."""
        if value is not None:
            self._attr_state = DISPLAY_STATES.get(value)
            self.async_write_ha_state()

    def _async_handle_media_playback_status(self, value: str | None) -> None:
        """Update entity attributes."""
        self._attr_state = MediaPlayerState.OFF if value is None else STATES.get(value)
        self.async_write_ha_state()

    def _async_handle_media_playback_source(self, value: str | None) -> None:
        """Update entity attributes."""
        self._attr_source = value
        self.async_write_ha_state()

    def _async_handle_media_audio_volume(self, value: float | None) -> None:
        """Update entity attributes."""
        self._attr_volume_level = None if value is None else value / VOLUME_FACTOR
        self.async_write_ha_state()

    def _async_handle_media_now_playing_duration(self, value: int | None) -> None:
        """Update entity attributes."""
        self._attr_media_duration = None if value is None else int(value / 1000)
        self.async_write_ha_state()

    def _async_handle_media_now_playing_elapsed(self, value: int | None) -> None:
        """Update entity attributes."""
        self._attr_media_position = None if value is None else int(value / 1000)
        self.async_write_ha_state()

    def _async_handle_media_now_playing_artist(self, value: str | None) -> None:
        """Update entity attributes."""
        self._attr_media_artist = value #Check if this is album artist or not
        self.async_write_ha_state()

    def _async_handle_media_now_playing_album(self, value: str | None) -> None:
        """Update entity attributes."""
        self._attr_media_album_name = value
        self.async_write_ha_state()

    def _async_handle_media_now_playing_title(self, value: str | None) -> None:
        """Update entity attributes."""
        self._attr_media_title = value
        self.async_write_ha_state()

    def _async_handle_media_now_playing_station(self, value: str | None) -> None:
        """Update entity attributes."""
        self._attr_media_channel = value # could also be _attr_media_playlist when Spotify
        self.async_write_ha_state()
