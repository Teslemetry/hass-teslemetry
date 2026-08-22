"""Local BLE data source for Teslemetry vehicles.

Values here come only from the vehicle's own Bluetooth link: unsolicited VCSEC
``VehicleStatus`` broadcasts, and parked-only INFO reads. Once a vehicle is BLE
paired, its rerouted entities are strictly local - they go unavailable on link
loss and never fall back to a stream or cloud value.

The INFO scheduler never connects, scans, or wakes the vehicle. It reads an
endpoint only while a link a command already opened is up and the vehicle
reports itself awake (VCSEC) and parked (streamed gear ``P``); after 15 minutes
without activity it disconnects and stays quiet until fresh awake-and-parked
evidence arrives.
"""

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from datetime import datetime, timedelta
from typing import Any, override

from bleak.exc import BleakError
from tesla_fleet_api.exceptions import TeslaFleetError
from tesla_fleet_api.router import VehicleRouter
from tesla_fleet_api.tesla.vehicle.bluetooth import VehicleBluetooth

# pylint: disable-next=no-name-in-module
from tesla_fleet_api.tesla.vehicle.proto.vcsec_pb2 import (
    UserPresence_E,
    VehicleSleepStatus_E,
)
from tesla_fleet_api.teslemetry import Vehicle
from teslemetry_stream.vehicle import TeslemetryStreamVehicle

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .entity import TeslemetryRootEntity
from .models import TeslemetryVehicleData

# How often the scheduler re-evaluates whether a due INFO read may run.
SCHEDULER_INTERVAL = timedelta(seconds=5)

# Minimum spacing between reads of a single endpoint.
INFO_REFRESH_INTERVAL = timedelta(seconds=60)

# Stop reading and disconnect after this long without a qualifying activity.
REST_AFTER = timedelta(minutes=15)

# Streamed gear value that means parked; every other value stops INFO reads.
PARKED_GEAR = "P"

type BroadcastRegister = Callable[
    [VehicleBluetooth, Callable[[Any], None]], Callable[[], None]
]
type InfoReader = Callable[[VehicleBluetooth], Awaitable[Any]]


class _InfoEndpoint:
    """A single parked-only INFO endpoint and its dependent entities."""

    def __init__(self, reader: InfoReader) -> None:
        """Initialize the endpoint around its single-endpoint reader."""
        self.reader = reader
        self.value: Any = None
        self.generation = -1
        self.last_read: datetime | None = None
        self.reading = False
        self.listeners: list[Callable[[Any, int], None]] = []


class TeslemetryBLEDataManager:
    """Own a vehicle's direct Bluetooth link and its locally sourced state.

    Broadcasts only arrive while the link a command opened is up, so a value is
    valid only within the connection generation it was received in. An
    unexpected drop bumps the generation, which makes every previously received
    value stale and its entity unavailable. INFO endpoints are read on the same
    live link, gated by the park/awake scheduler.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        bluetooth: VehicleBluetooth,
        stream_vehicle: TeslemetryStreamVehicle,
        vin: str,
    ) -> None:
        """Initialize the manager around an already-created BLE client."""
        self.hass = hass
        self.vin = vin
        self._bluetooth = bluetooth
        self._stream_vehicle = stream_vehicle
        self._generation = 0
        self._connected = False
        self._connection_listeners: list[Callable[[], None]] = []
        self._unsub_connection: Callable[[], None] | None = None
        self._unsub_scheduler: Callable[[], None] | None = None
        self._gate_unsubs: list[Callable[[], None]] = []
        # Scheduler gate state; ``None`` means unknown, which never permits a read.
        self._awake: bool | None = None
        self._parked: bool | None = None
        self._resting = False
        self._last_activity = dt_util.utcnow()
        self._info_lock = asyncio.Lock()
        self._endpoints: dict[str, _InfoEndpoint] = {}

    @property
    def bluetooth(self) -> VehicleBluetooth:
        """Return the direct BLE client, never the command router."""
        return self._bluetooth

    @property
    def generation(self) -> int:
        """Return the current connection generation."""
        return self._generation

    @property
    def connected(self) -> bool:
        """Return whether the BLE link is currently up."""
        return self._connected

    @callback
    def async_start(self) -> None:
        """Subscribe to connection and gate signals, and run the INFO scheduler."""
        self._unsub_connection = self._bluetooth.listen_connection_status(
            self._handle_connection_status
        )
        self._unsub_scheduler = async_track_time_interval(
            self.hass, self._async_scheduler_tick, SCHEDULER_INTERVAL
        )
        b = self._bluetooth
        s = self._stream_vehicle
        self._gate_unsubs = [
            b.listen_vehicle_sleep_status(self._handle_sleep),
            b.listen_user_presence(self._handle_user_present),
            s.listen_Gear(self._handle_gear),
            s.listen_DetailedChargeState(self._handle_charge),
            s.listen_SentryMode(self._handle_sentry),
        ]

    @callback
    def async_stop(self) -> None:
        """Stop all timers and listeners on unload."""
        if self._unsub_connection is not None:
            self._unsub_connection()
            self._unsub_connection = None
        if self._unsub_scheduler is not None:
            self._unsub_scheduler()
            self._unsub_scheduler = None
        for unsub in self._gate_unsubs:
            unsub()
        self._gate_unsubs = []

    @callback
    def _handle_connection_status(self, connected: bool) -> None:
        """Drive cached link state from the library's connection event.

        The library fires only genuine transitions and owns the stale-client
        identity guard, so this just records the new state and, on a drop, bumps
        the generation to make every value from the lost link stale.
        """
        if not connected:
            self._generation += 1
        self._connected = connected
        self._async_notify_connection()

    @callback
    def _async_notify_connection(self) -> None:
        """Tell every entity to re-evaluate availability."""
        for listener in list(self._connection_listeners):
            listener()

    @callback
    def async_on_connection_change(
        self, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback fired when the link comes up or drops."""
        self._connection_listeners.append(listener)

        @callback
        def remove() -> None:
            self._connection_listeners.remove(listener)

        return remove

    @callback
    def async_on_broadcast(
        self,
        register: BroadcastRegister,
        convert: Callable[[Any], Any],
        update: Callable[[Any, int], None],
    ) -> Callable[[], None]:
        """Subscribe an entity to one VCSEC broadcast field.

        ``register`` attaches the library's typed listener; ``convert`` maps the
        raw protobuf value to the entity value (``None`` for an unknown enum);
        ``update`` receives ``(value, generation)``.
        """

        @callback
        def handle(raw: Any) -> None:
            update(convert(raw), self._generation)

        return register(self._bluetooth, handle)

    @callback
    def async_on_endpoint(
        self,
        name: str,
        reader: InfoReader,
        update: Callable[[Any, int], None],
    ) -> Callable[[], None]:
        """Subscribe an entity to a parked-only INFO endpoint.

        ``reader`` issues the single-endpoint request; ``update`` receives
        ``(value, generation)``, with ``value`` ``None`` while unavailable.
        """
        endpoint = self._endpoints.get(name)
        if endpoint is None:
            endpoint = _InfoEndpoint(reader)
            self._endpoints[name] = endpoint
        endpoint.listeners.append(update)
        update(endpoint.value, endpoint.generation)

        @callback
        def remove() -> None:
            endpoint.listeners.remove(update)
            if not endpoint.listeners:
                self._endpoints.pop(name, None)

        return remove

    @callback
    def _notify_endpoint(self, endpoint: _InfoEndpoint) -> None:
        """Push an endpoint's current value to its dependent entities."""
        for listener in list(endpoint.listeners):
            listener(endpoint.value, endpoint.generation)

    @callback
    def _handle_sleep(self, value: int) -> None:
        """Track VCSEC sleep as the hard read gate."""
        if value == VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_AWAKE:
            self._awake = True
            self._mark_activity()
        elif value == VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_ASLEEP:
            self._awake = False
            self._async_stop_info()
        else:
            self._awake = None
            self._async_stop_info()

    @callback
    def _handle_gear(self, gear: str | None) -> None:
        """Track streamed gear; only ``P`` permits a read."""
        if gear == PARKED_GEAR:
            self._parked = True
        elif gear is None:
            self._parked = None
            self._async_stop_info()
        else:
            self._parked = False
            self._async_stop_info()

    @callback
    def _handle_user_present(self, value: int) -> None:
        """A present user extends the active window."""
        if value == UserPresence_E.VEHICLE_USER_PRESENCE_PRESENT:
            self._mark_activity()

    @callback
    def _handle_charge(self, value: str | None) -> None:
        """Active charging extends the active window."""
        if value == "Charging":
            self._mark_activity()

    @callback
    def _handle_sentry(self, value: str | None) -> None:
        """Active sentry extends the active window."""
        if value not in (None, "Off", "Unknown"):
            self._mark_activity()

    @callback
    def _mark_activity(self) -> None:
        """Reset the inactivity timer and allow reading again."""
        self._last_activity = dt_util.utcnow()
        self._resting = False

    @callback
    def _async_stop_info(self) -> None:
        """Mark every endpoint unavailable without disconnecting the link."""
        for endpoint in self._endpoints.values():
            if endpoint.value is not None:
                endpoint.value = None
                self._notify_endpoint(endpoint)

    @callback
    def _enter_rest(self) -> None:
        """Stop reading and disconnect after the inactivity window."""
        if self._resting:
            return
        self._resting = True
        self._async_stop_info()
        self.hass.async_create_task(self._async_disconnect())

    async def _async_disconnect(self) -> None:
        """Drop the link so the vehicle can sleep; never surface failures."""
        with contextlib.suppress(BleakError, TeslaFleetError, TimeoutError):
            await self._bluetooth.disconnect()

    @callback
    def _async_scheduler_tick(self, now: datetime) -> None:
        """Read any due endpoint while awake and parked, or rest when idle."""
        if self._resting or not (
            self._connected and self._awake is True and self._parked is True
        ):
            return
        if dt_util.utcnow() - self._last_activity >= REST_AFTER:
            self._enter_rest()
            return
        for endpoint in self._endpoints.values():
            if endpoint.reading:
                continue
            if (
                endpoint.last_read is None
                or dt_util.utcnow() - endpoint.last_read >= INFO_REFRESH_INTERVAL
            ):
                self.hass.async_create_task(self._async_read_endpoint(endpoint))

    async def _async_read_endpoint(self, endpoint: _InfoEndpoint) -> None:
        """Read one endpoint under the shared lock so reads never overlap."""
        endpoint.reading = True
        generation = self._generation
        try:
            async with self._info_lock:
                if (
                    generation != self._generation
                    or self._resting
                    or not (self._connected and self._awake and self._parked)
                ):
                    return
                result = await endpoint.reader(self._bluetooth)
        except TeslaFleetError:
            endpoint.value = None
            self._notify_endpoint(endpoint)
            return
        finally:
            endpoint.reading = False
        # A drop while the read was in flight invalidates its result.
        if generation != self._generation:
            return
        endpoint.value = result
        endpoint.generation = generation
        endpoint.last_read = dt_util.utcnow()
        self._notify_endpoint(endpoint)


class TeslemetryVehicleBluetoothEntity(TeslemetryRootEntity):
    """Parent class for entities sourced from a vehicle's local BLE data."""

    manager: TeslemetryBLEDataManager
    api: Vehicle | VehicleRouter
    _value: Any = None
    _generation: int = -1

    def __init__(self, data: TeslemetryVehicleData, key: str) -> None:
        """Initialize common aspects of a Teslemetry BLE entity."""
        assert data.ble is not None
        self.vehicle = data
        self.manager = data.ble
        self.config_entry = data.config_entry
        # Commands still route through the router; only reads are local.
        self.api = data.api
        self.vin = data.vin
        self._attr_translation_key = key
        self._attr_unique_id = f"{data.vin}-{key}"
        self._attr_device_info = data.device

    @override
    async def async_added_to_hass(self) -> None:
        """Re-evaluate availability whenever the link comes up or drops."""
        self.async_on_remove(
            self.manager.async_on_connection_change(self._handle_connection_change)
        )

    @callback
    def _handle_connection_change(self) -> None:
        """Handle the link coming up or dropping."""
        self.async_write_ha_state()

    @callback
    def _handle_broadcast(self, value: Any, generation: int) -> None:
        """Store a freshly received value and its generation."""
        self._value = value
        self._generation = generation
        self.async_write_ha_state()

    @property
    @override
    def available(self) -> bool:
        """Return True only for a value received on the current live link."""
        return (
            self.manager.connected
            and self._generation == self.manager.generation
            and self._value is not None
        )
