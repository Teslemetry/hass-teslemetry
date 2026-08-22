"""Test the Teslemetry BLE broadcast data source."""

from collections.abc import Callable
from copy import deepcopy
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest

# pylint: disable-next=no-name-in-module
from tesla_fleet_api.tesla.vehicle.proto.vcsec_pb2 import (
    ClosureState_E,
    UserPresence_E,
    VehicleLockState_E,
    VehicleSleepStatus_E,
)

# pylint: disable-next=no-name-in-module
from tesla_fleet_api.tesla.vehicle.proto.vehicle_pb2 import ClosuresState
from teslemetry_stream import Signal

from homeassistant.components.lock import LockState
from homeassistant.components.teslemetry.const import CONF_VIN, SUBENTRY_TYPE_VEHICLE
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import (
    CONF_ADDRESS,
    STATE_CLOSED,
    STATE_OFF,
    STATE_ON,
    STATE_OPEN,
    STATE_UNAVAILABLE,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from . import mock_config_entry, setup_platform
from .const import PRODUCTS

from tests.common import MockConfigEntry, async_fire_time_changed

VIN = "LRW3F7EK4NC700000"
ADDRESS = "AA:BB:CC:DD:EE:FF"


def _entry_with_ble() -> MockConfigEntry:
    """Return a config entry whose vehicle subentry is already BLE-paired."""
    entry = mock_config_entry()
    return MockConfigEntry(
        domain=entry.domain,
        version=entry.version,
        minor_version=entry.minor_version,
        unique_id=entry.unique_id,
        data=dict(entry.data),
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_VEHICLE,
                unique_id=VIN,
                title="Test",
                data={CONF_VIN: VIN, CONF_ADDRESS: ADDRESS},
            )
        ],
    )


async def _setup_ble(
    hass: HomeAssistant,
    connected: bool = True,
    platforms: tuple[Platform, ...] = (Platform.BINARY_SENSOR,),
    sunroof: bool = False,
) -> tuple[MockConfigEntry, MagicMock]:
    """Set up the given platforms for a BLE-paired vehicle.

    Returns the entry and the BLE client mock. The client's ``listen_*`` methods
    record the manager's broadcast callbacks so tests can feed them raw values;
    ``listen_connection_status`` records the manager's connection callback. When
    ``connected`` the link is brought up via that callback, as the library does
    once a session is established. ``sunroof`` reports the vehicle's metadata as
    sunroof-installed.
    """
    entry = _entry_with_ble()
    entry.add_to_hass(hass)
    bluetooth_vehicle = MagicMock()
    bluetooth_vehicle.client = MagicMock()
    bluetooth_vehicle.disconnect = AsyncMock()

    products = deepcopy(PRODUCTS)
    if sunroof:
        products["response"][0]["vehicle_config"]["sun_roof_installed"] = True

    with (
        patch(
            "homeassistant.components.teslemetry.async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch(
            "homeassistant.components.teslemetry.helpers.TeslaBluetooth"
        ) as mock_parent,
        patch("homeassistant.components.teslemetry.PLATFORMS", list(platforms)),
        patch("tesla_fleet_api.teslemetry.Teslemetry.products", return_value=products),
    ):
        mock_parent.return_value.get_private_key = AsyncMock()
        mock_parent.return_value.vehicles.createBluetooth.return_value = (
            bluetooth_vehicle
        )
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    if connected:
        _emit_connection(bluetooth_vehicle, True)
        await hass.async_block_till_done()

    return entry, bluetooth_vehicle


def _emit(mock_listener: MagicMock, value: Any) -> None:
    """Invoke the manager's captured broadcast callback with a raw value."""
    callback: Callable[[Any], None] = mock_listener.call_args[0][0]
    callback(value)


def _emit_connection(bluetooth: MagicMock, connected: bool) -> None:
    """Fire the library's connection-status callback the manager subscribed with."""
    listener = bluetooth.listen_connection_status
    callback: Callable[[bool], None] = listener.call_args[0][0]
    callback(connected)


async def test_paired_vehicle_uses_broadcasts(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A paired vehicle sources its rerouted sensors from BLE broadcasts."""
    entry, bluetooth = await _setup_ble(hass)
    assert entry.runtime_data.vehicles[0].ble is not None

    state_id = entity_registry.async_get_entity_id(
        "binary_sensor", "teslemetry", f"{VIN}-state"
    )
    assert state_id is not None
    # No broadcast yet: strictly local, so unavailable rather than a stream value.
    assert hass.states.get(state_id).state == STATE_UNAVAILABLE

    _emit(
        bluetooth.listen_vehicle_sleep_status,
        VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_AWAKE,
    )
    await hass.async_block_till_done()
    assert hass.states.get(state_id).state == STATE_ON

    _emit(
        bluetooth.listen_vehicle_sleep_status,
        VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_ASLEEP,
    )
    await hass.async_block_till_done()
    assert hass.states.get(state_id).state == STATE_OFF


async def test_unpaired_vehicle_not_bluetooth(hass: HomeAssistant) -> None:
    """Without a paired address a vehicle has no BLE data manager."""
    entry = await setup_platform(hass, [Platform.BINARY_SENSOR])
    assert entry.runtime_data.vehicles[0].ble is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (ClosureState_E.CLOSURESTATE_CLOSED, STATE_OFF),
        (ClosureState_E.CLOSURESTATE_OPEN, STATE_ON),
        (ClosureState_E.CLOSURESTATE_AJAR, STATE_ON),
        (ClosureState_E.CLOSURESTATE_OPENING, STATE_ON),
        (ClosureState_E.CLOSURESTATE_CLOSING, STATE_ON),
        (ClosureState_E.CLOSURESTATE_UNKNOWN, STATE_UNAVAILABLE),
        (ClosureState_E.CLOSURESTATE_FAILED_UNLATCH, STATE_UNAVAILABLE),
    ],
)
async def test_door_closure_conversion(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    raw: int,
    expected: str,
) -> None:
    """Each door closure enum maps to the right binary state; unknown is unavailable."""
    _entry, bluetooth = await _setup_ble(hass)
    door_id = entity_registry.async_get_entity_id(
        "binary_sensor", "teslemetry", f"{VIN}-vehicle_state_df"
    )

    _emit(bluetooth.listen_front_driver_door, raw)
    await hass.async_block_till_done()
    assert hass.states.get(door_id).state == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (UserPresence_E.VEHICLE_USER_PRESENCE_PRESENT, STATE_ON),
        (UserPresence_E.VEHICLE_USER_PRESENCE_NOT_PRESENT, STATE_OFF),
        (UserPresence_E.VEHICLE_USER_PRESENCE_UNKNOWN, STATE_UNAVAILABLE),
    ],
)
async def test_user_presence_conversion(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    raw: int,
    expected: str,
) -> None:
    """User presence maps present/not-present to on/off; unknown is unavailable."""
    _entry, bluetooth = await _setup_ble(hass)
    presence_id = entity_registry.async_get_entity_id(
        "binary_sensor", "teslemetry", f"{VIN}-vehicle_state_is_user_present"
    )

    _emit(bluetooth.listen_user_presence, raw)
    await hass.async_block_till_done()
    assert hass.states.get(presence_id).state == expected


async def test_unknown_sleep_never_false(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A default/unknown sleep enum is unavailable, never a false 'asleep'."""
    _entry, bluetooth = await _setup_ble(hass)
    state_id = entity_registry.async_get_entity_id(
        "binary_sensor", "teslemetry", f"{VIN}-state"
    )

    _emit(
        bluetooth.listen_vehicle_sleep_status,
        VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_UNKNOWN,
    )
    await hass.async_block_till_done()
    assert hass.states.get(state_id).state == STATE_UNAVAILABLE


async def test_link_loss_marks_unavailable(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A library disconnect event makes every broadcast sensor unavailable."""
    _entry, bluetooth = await _setup_ble(hass)
    state_id = entity_registry.async_get_entity_id(
        "binary_sensor", "teslemetry", f"{VIN}-state"
    )

    _emit(
        bluetooth.listen_vehicle_sleep_status,
        VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_AWAKE,
    )
    await hass.async_block_till_done()
    assert hass.states.get(state_id).state == STATE_ON

    _emit_connection(bluetooth, False)
    await hass.async_block_till_done()
    assert hass.states.get(state_id).state == STATE_UNAVAILABLE


async def test_broadcast_without_connection_stays_unavailable(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A broadcast alone no longer implies the link is up; state stays unavailable."""
    _entry, bluetooth = await _setup_ble(hass, connected=False)
    state_id = entity_registry.async_get_entity_id(
        "binary_sensor", "teslemetry", f"{VIN}-state"
    )

    _emit(
        bluetooth.listen_vehicle_sleep_status,
        VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_AWAKE,
    )
    await hass.async_block_till_done()
    assert hass.states.get(state_id).state == STATE_UNAVAILABLE

    # Only the library's connection event brings the sensor online.
    _emit_connection(bluetooth, True)
    _emit(
        bluetooth.listen_vehicle_sleep_status,
        VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_AWAKE,
    )
    await hass.async_block_till_done()
    assert hass.states.get(state_id).state == STATE_ON


async def test_reconnect_invalidates_stale_value(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A value from a prior connection stays unavailable until a fresh broadcast."""
    _entry, bluetooth = await _setup_ble(hass)
    state_id = entity_registry.async_get_entity_id(
        "binary_sensor", "teslemetry", f"{VIN}-state"
    )

    _emit(
        bluetooth.listen_vehicle_sleep_status,
        VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_AWAKE,
    )
    await hass.async_block_till_done()
    assert hass.states.get(state_id).state == STATE_ON

    _emit_connection(bluetooth, False)
    await hass.async_block_till_done()
    assert hass.states.get(state_id).state == STATE_UNAVAILABLE

    # The link is back, but the pre-drop value is stale until a new broadcast.
    _emit_connection(bluetooth, True)
    await hass.async_block_till_done()
    assert hass.states.get(state_id).state == STATE_UNAVAILABLE

    _emit(
        bluetooth.listen_vehicle_sleep_status,
        VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_AWAKE,
    )
    await hass.async_block_till_done()
    assert hass.states.get(state_id).state == STATE_ON


async def test_no_info_requests(hass: HomeAssistant) -> None:
    """A broadcast-only vehicle issues no BLE INFO reads."""
    _entry, bluetooth = await _setup_ble(hass)

    bluetooth.vehicle_data.assert_not_called()
    bluetooth.closures_state.assert_not_called()
    bluetooth.climate_state.assert_not_called()


@pytest.mark.parametrize(
    ("listener", "entity_key"),
    [
        ("listen_charge_port", "charge_state_charge_port_door_open"),
        ("listen_front_trunk", "vehicle_state_ft"),
        ("listen_rear_trunk", "vehicle_state_rt"),
    ],
)
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (ClosureState_E.CLOSURESTATE_CLOSED, STATE_CLOSED),
        (ClosureState_E.CLOSURESTATE_OPEN, STATE_OPEN),
        (ClosureState_E.CLOSURESTATE_AJAR, STATE_OPEN),
        (ClosureState_E.CLOSURESTATE_OPENING, STATE_OPEN),
        (ClosureState_E.CLOSURESTATE_CLOSING, STATE_OPEN),
        (ClosureState_E.CLOSURESTATE_UNKNOWN, STATE_UNAVAILABLE),
        (ClosureState_E.CLOSURESTATE_FAILED_UNLATCH, STATE_UNAVAILABLE),
    ],
)
async def test_cover_closure_conversion(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    listener: str,
    entity_key: str,
    raw: int,
    expected: str,
) -> None:
    """Each broadcast cover maps its closure enum; unknown is unavailable."""
    _entry, bluetooth = await _setup_ble(hass, platforms=(Platform.COVER,))
    cover_id = entity_registry.async_get_entity_id(
        "cover", "teslemetry", f"{VIN}-{entity_key}"
    )
    assert cover_id is not None

    _emit(getattr(bluetooth, listener), raw)
    await hass.async_block_till_done()
    assert hass.states.get(cover_id).state == expected


async def test_cover_link_loss_marks_unavailable(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A broadcast cover goes unavailable on link loss with no cloud fallback."""
    _entry, bluetooth = await _setup_ble(
        hass, connected=True, platforms=(Platform.COVER,)
    )
    cover_id = entity_registry.async_get_entity_id(
        "cover", "teslemetry", f"{VIN}-vehicle_state_ft"
    )

    _emit(bluetooth.listen_front_trunk, ClosureState_E.CLOSURESTATE_CLOSED)
    await hass.async_block_till_done()
    assert hass.states.get(cover_id).state == STATE_CLOSED

    _emit_connection(bluetooth, False)
    await hass.async_block_till_done()
    assert hass.states.get(cover_id).state == STATE_UNAVAILABLE


async def test_cover_command_routes_through_api(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A broadcast cover still sends its command through the command router."""
    entry, bluetooth = await _setup_ble(
        hass, connected=True, platforms=(Platform.COVER,)
    )
    cover_id = entity_registry.async_get_entity_id(
        "cover", "teslemetry", f"{VIN}-charge_state_charge_port_door_open"
    )

    _emit(bluetooth.listen_charge_port, ClosureState_E.CLOSURESTATE_CLOSED)
    await hass.async_block_till_done()

    router = entry.runtime_data.vehicles[0].api
    router.charge_port_door_open = AsyncMock(
        return_value={"response": {"result": True, "reason": ""}}
    )
    await hass.services.async_call(
        "cover", "open_cover", {"entity_id": cover_id}, blocking=True
    )
    router.charge_port_door_open.assert_awaited_once()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (VehicleLockState_E.VEHICLELOCKSTATE_LOCKED, LockState.LOCKED),
        (VehicleLockState_E.VEHICLELOCKSTATE_INTERNAL_LOCKED, LockState.LOCKED),
        (VehicleLockState_E.VEHICLELOCKSTATE_UNLOCKED, LockState.UNLOCKED),
        (VehicleLockState_E.VEHICLELOCKSTATE_SELECTIVE_UNLOCKED, LockState.UNLOCKED),
        (99, STATE_UNAVAILABLE),
    ],
)
async def test_lock_state_conversion(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    raw: int,
    expected: str,
) -> None:
    """The vehicle lock maps its VCSEC enum; an unrecognized value is unavailable."""
    _entry, bluetooth = await _setup_ble(hass, platforms=(Platform.LOCK,))
    lock_id = entity_registry.async_get_entity_id(
        "lock", "teslemetry", f"{VIN}-vehicle_state_locked"
    )
    assert lock_id is not None

    _emit(bluetooth.listen_vehicle_lock_state, raw)
    await hass.async_block_till_done()
    assert hass.states.get(lock_id).state == expected


async def test_lock_link_loss_marks_unavailable(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """The broadcast vehicle lock goes unavailable on link loss, no cloud fallback."""
    _entry, bluetooth = await _setup_ble(
        hass, connected=True, platforms=(Platform.LOCK,)
    )
    lock_id = entity_registry.async_get_entity_id(
        "lock", "teslemetry", f"{VIN}-vehicle_state_locked"
    )

    _emit(
        bluetooth.listen_vehicle_lock_state, VehicleLockState_E.VEHICLELOCKSTATE_LOCKED
    )
    await hass.async_block_till_done()
    assert hass.states.get(lock_id).state == LockState.LOCKED

    _emit_connection(bluetooth, False)
    await hass.async_block_till_done()
    assert hass.states.get(lock_id).state == STATE_UNAVAILABLE


def _closures(sunroof: str | None, percent: int = 0) -> ClosuresState:
    """Build a BLE closures snapshot with a sunroof oneof case and position."""
    closures = ClosuresState(sun_roof_percent_open=percent)
    if sunroof is not None:
        getattr(closures.sun_roof_state, sunroof).SetInParent()
    return closures


def _make_active(bluetooth: MagicMock, mock_add_listener: MagicMock) -> None:
    """Drive the manager to connected, awake, and parked."""
    # A broadcast proves the link is up.
    _emit(bluetooth.listen_charge_port, ClosureState_E.CLOSURESTATE_CLOSED)
    # On a cover-only setup the manager is the only sleep/gear listener.
    _emit(
        bluetooth.listen_vehicle_sleep_status,
        VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_AWAKE,
    )
    mock_add_listener.send({"vin": VIN, "data": {Signal.GEAR: "P"}})


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_sunroof_reads_when_parked_and_awake(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_add_listener: MagicMock,
) -> None:
    """A parked, awake vehicle reads the sunroof over a single closures snapshot."""
    _entry, bluetooth = await _setup_ble(
        hass, connected=True, platforms=(Platform.COVER,), sunroof=True
    )
    sunroof_id = entity_registry.async_get_entity_id(
        "cover", "teslemetry", f"{VIN}-vehicle_state_sun_roof_state"
    )
    assert sunroof_id is not None
    assert hass.states.get(sunroof_id).state == STATE_UNAVAILABLE

    bluetooth.closures_state = AsyncMock(return_value=_closures("Closed", 20))
    _make_active(bluetooth, mock_add_listener)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()

    bluetooth.closures_state.assert_awaited_once()
    bluetooth.vehicle_data.assert_not_called()
    state = hass.states.get(sunroof_id)
    assert state.state == STATE_CLOSED
    assert state.attributes["current_position"] == 20


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    ("sleep", "gear"),
    [
        (VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_AWAKE, "D"),
        (VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_AWAKE, "Unknown"),
        (VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_ASLEEP, "P"),
        (VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_UNKNOWN, "P"),
    ],
)
async def test_sunroof_gate_blocks_reads(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_add_listener: MagicMock,
    sleep: int,
    gear: str,
) -> None:
    """Neither a moving nor an asleep vehicle issues an INFO read."""
    _entry, bluetooth = await _setup_ble(
        hass, connected=True, platforms=(Platform.COVER,), sunroof=True
    )
    sunroof_id = entity_registry.async_get_entity_id(
        "cover", "teslemetry", f"{VIN}-vehicle_state_sun_roof_state"
    )
    bluetooth.closures_state = AsyncMock(return_value=_closures("Closed"))

    _emit(bluetooth.listen_charge_port, ClosureState_E.CLOSURESTATE_CLOSED)
    _emit(bluetooth.listen_vehicle_sleep_status, sleep)
    mock_add_listener.send({"vin": VIN, "data": {Signal.GEAR: gear}})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()

    bluetooth.closures_state.assert_not_called()
    assert hass.states.get(sunroof_id).state == STATE_UNAVAILABLE


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_sunroof_rests_and_disconnects_after_idle(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_add_listener: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """After 15 idle minutes the manager stops reading and disconnects."""
    _entry, bluetooth = await _setup_ble(
        hass, connected=True, platforms=(Platform.COVER,), sunroof=True
    )
    sunroof_id = entity_registry.async_get_entity_id(
        "cover", "teslemetry", f"{VIN}-vehicle_state_sun_roof_state"
    )

    bluetooth.closures_state = AsyncMock(return_value=_closures("Closed"))
    _make_active(bluetooth, mock_add_listener)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert hass.states.get(sunroof_id).state == STATE_CLOSED

    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    bluetooth.disconnect.assert_awaited()
    assert bluetooth.closures_state.await_count == 1
    # The manager also marks the link down once disconnect takes effect.
    _emit_connection(bluetooth, False)
    await hass.async_block_till_done()
    assert hass.states.get(sunroof_id).state == STATE_UNAVAILABLE


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_sunroof_absent_makes_no_reads(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_add_listener: MagicMock,
) -> None:
    """A vehicle without a sunroof has no entity and issues no INFO reads."""
    _entry, bluetooth = await _setup_ble(
        hass, connected=True, platforms=(Platform.COVER,), sunroof=False
    )
    assert (
        entity_registry.async_get_entity_id(
            "cover", "teslemetry", f"{VIN}-vehicle_state_sun_roof_state"
        )
        is None
    )

    bluetooth.closures_state = AsyncMock(return_value=_closures("Closed"))
    _make_active(bluetooth, mock_add_listener)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()

    bluetooth.closures_state.assert_not_called()
