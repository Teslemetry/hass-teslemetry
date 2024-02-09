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

from .const import DOMAIN
from .entity import (
    TeslemetryVehicleEntity,
)
from .models import TeslemetryVehicleData
from .context import handle_command

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
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        TeslemetryMediaEntity(vehicle, Scope.VEHICLE_CMDS in data.scopes)
        for vehicle in data.vehicles
    )


class TeslemetryMediaEntity(TeslemetryVehicleEntity, MediaPlayerEntity):
    """Vehicle Location Media Class."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_supported_features = (
        MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.VOLUME_SET
    )

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

    @property
    def max_volume(self) -> float:
        """Return the maximum volume level."""
        return self.get("vehicle_state_media_info_audio_volume_max", MAX_VOLUME)

    @property
    def state(self) -> MediaPlayerState:
        """State of the player."""
        return STATES.get(
            self.get("vehicle_state_media_info_media_playback_status"),
            MediaPlayerState.OFF,
        )

    @property
    def volume_step(self) -> float:
        """Volume step size."""
        return (
            1.0
            / self.max_volume
            / self.get("vehicle_state_media_info_audio_volume_increment", 1.0 / 3)
        )

    @property
    def volume_level(self) -> float:
        """Volume level of the media player (0..1)."""
        return self.get("vehicle_state_media_info_audio_volume", 0) / self.max_volume

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        if duration := self.get("vehicle_state_media_info_now_playing_duration"):
            return duration / 1000
        return None

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds."""
        # Return media position only when a media duration is > 0
        if self.get("vehicle_state_media_info_now_playing_duration"):
            return self.get("vehicle_state_media_info_now_playing_elapsed") / 1000
        return None

    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        return self.get("vehicle_state_media_info_now_playing_title")

    @property
    def media_artist(self) -> str | None:
        """Artist of current playing media, music track only."""
        return self.get("vehicle_state_media_info_now_playing_artist")

    @property
    def media_album_name(self) -> str | None:
        """Album name of current playing media, music track only."""
        return self.get("vehicle_state_media_info_now_playing_album")

    @property
    def media_playlist(self) -> str | None:
        """Title of Playlist currently playing."""
        return self.get("vehicle_state_media_info_now_playing_station")

    @property
    def source(self) -> str | None:
        """Name of the current input source."""
        return self.get("vehicle_state_media_info_now_playing_source")

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.adjust_volume(int(volume * self.max_volume)))

    async def async_media_play(self) -> None:
        """Send play command."""
        if self.state != MediaPlayerState.PLAYING:
            self.raise_for_scope()
            await self.wake_up_if_asleep()
            await self.handle_command(await self.api.media_toggle_playback())

    async def async_media_pause(self) -> None:
        """Send pause command."""
        if self.state == MediaPlayerState.PLAYING:
            self.raise_for_scope()
            await self.wake_up_if_asleep()
            await self.handle_command(await self.api.media_toggle_playback())

    async def async_media_next_track(self) -> None:
        """Send next track command."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.media_next_track())

    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        await self.handle_command(self.api.media_previous_track())
