"""Media Player platform for Teslemetry integration."""
from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerState,
    MediaPlayerEntityFeature
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, Scopes
from .entity import (
    TeslemetryVehicleEntity,
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
    data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        TeslemetryMediaEntity(vehicle, Scopes.VEHICLE_CMDS in data.scopes) for vehicle in data.vehicles
    )


class TeslemetryMediaEntity(TeslemetryVehicleEntity, MediaPlayerEntity):
    """Vehicle Location Media Class."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_supported_features = MediaPlayerEntityFeature.NEXT_TRACK | MediaPlayerEntityFeature.PAUSE | MediaPlayerEntityFeature.PLAY | MediaPlayerEntityFeature.PREVIOUS_TRACK | MediaPlayerEntityFeature.VOLUME_SET

    def __init__(
        self,
        vehicle: TeslemetryVehicleData,
        scoped: bool,
    ) -> None:
        """Initialize the media player entity."""
        super().__init__(vehicle, "media")
        self.scoped = scoped
        if not scoped:
            _attr_supported_features = MediaPlayerEntityFeature(0)

    @property
    def state(self) -> MediaPlayerState:
        """State of the player."""
        return STATES.get(
            self.get("vehicle_state_media_info_media_playback_status"),
            MediaPlayerState.OFF,
        )

    @property
    def volume_level(self) -> float:
        """Volume level of the media player (0..1)."""
        return self.get("vehicle_state_media_info_audio_volume", 0) / self.get(
            "vehicle_state_media_info_audio_volume_max", MAX_VOLUME
        )

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
        await self.api.adjust_volume(int(volume * self.get("vehicle_state_media_info_audio_volume_max", MAX_VOLUME)))



