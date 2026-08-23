"""Multi-source observation funnel for Teslemetry vehicles.

One :class:`ObservationFunnel` per BLE-paired vehicle fans values from the
library's ``BleBroadcastPublisher`` and ``VehicleDataResultPublisher`` into a
single listener set, so a field survives the loss of either source. Unlike the
strictly-local BLE path in ``ble.py``, a value here is not tied to a connection
generation: only a source reporting a field unavailable clears it.
"""

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, override

from tesla_fleet_api.funnel import (
    BleBroadcastPublisher,
    FieldPath,
    ObservationFunnel,
    VehicleDataResultPublisher,
)
from tesla_fleet_api.router import VehicleRouter
from tesla_fleet_api.tesla.vehicle.bluetooth import VehicleBluetooth
from tesla_fleet_api.teslemetry import Vehicle

from homeassistant.core import callback

from .coordinator import TeslemetryVehicleDataCoordinator
from .entity import TeslemetryRootEntity
from .models import TeslemetryVehicleData

if TYPE_CHECKING:
    from . import TeslemetryConfigEntry

# The fields the integration currently routes through the funnel. ``LOCKED`` is
# a defined FieldPath but stays on the single-source BLE path in ble.py: the
# library's BleBroadcastPublisher maps only LOCKED/UNLOCKED, so adopting it here
# would drop INTERNAL_LOCKED and SELECTIVE_UNLOCKED in the BLE-only parked case.
FUNNEL_PATHS = frozenset(
    {FieldPath.CHARGE_PORT_DOOR_OPEN, FieldPath.DOOR_STATE_TRUNK_FRONT}
)


def _vehicle_data_result(data: Mapping[str, Any]) -> dict[str, Any]:
    """Re-nest the funnel's leaves from the coordinator's flattened store.

    The coordinator flattens vehicle_data (see helpers.flatten); the library
    publisher reads a nested result, so present just the leaves it maps here. A
    key absent from the flat store stays absent so it is not read as a null.
    """
    vehicle_state: dict[str, Any] = {}
    charge_state: dict[str, Any] = {}
    if "vehicle_state_ft" in data:
        vehicle_state["ft"] = data["vehicle_state_ft"]
    if "charge_state_charge_port_door_open" in data:
        charge_state["charge_port_door_open"] = data[
            "charge_state_charge_port_door_open"
        ]
    return {"vehicle_state": vehicle_state, "charge_state": charge_state}


@callback
def async_setup_funnel(
    entry: TeslemetryConfigEntry,
    bluetooth: VehicleBluetooth,
    coordinator: TeslemetryVehicleDataCoordinator,
) -> ObservationFunnel:
    """Build a vehicle's funnel, attach both publishers, and wire demand.

    Returns the funnel; every teardown is registered on ``entry.async_on_unload``
    so no publisher or listener survives an unload. The BLE publisher's own
    request/release (driven by :meth:`ObservationFunnel.listen`) subscribes to
    the vehicle's broadcasts only while a field is listened to; a demand
    observer gates the vehicle_data feed the same way.
    """
    funnel = ObservationFunnel()
    entry.async_on_unload(funnel.attach(BleBroadcastPublisher(bluetooth)))
    data_publisher = VehicleDataResultPublisher()
    entry.async_on_unload(funnel.attach(data_publisher))

    unsub_coordinator: Callable[[], None] | None = None

    @callback
    def _feed() -> None:
        data_publisher.publish_result(_vehicle_data_result(coordinator.data))

    @callback
    def _detach_coordinator() -> None:
        nonlocal unsub_coordinator
        if unsub_coordinator is not None:
            unsub_coordinator()
            unsub_coordinator = None

    @callback
    def _on_demand(active: bool) -> None:
        nonlocal unsub_coordinator
        if active and unsub_coordinator is None:
            unsub_coordinator = coordinator.async_add_listener(_feed)
            _feed()
        elif not active:
            _detach_coordinator()

    entry.async_on_unload(funnel.listen_demand(FUNNEL_PATHS, _on_demand))
    entry.async_on_unload(_detach_coordinator)
    return funnel


class TeslemetryVehicleFunnelEntity(TeslemetryRootEntity):
    """Parent class for an entity served one field by the vehicle's funnel.

    Availability tracks whether the funnel holds a value for the field, not any
    BLE connection: the value survives the loss of any single source.
    """

    api: Vehicle | VehicleRouter
    _value: bool | None = None

    def __init__(self, data: TeslemetryVehicleData, key: str, field: FieldPath) -> None:
        """Initialize common aspects of a funnel-backed entity."""
        assert data.funnel is not None
        self.funnel = data.funnel
        self._field = field
        # Commands still route through the router; only reads are funnelled.
        self.config_entry = data.config_entry
        self.api = data.api
        self.vin = data.vin
        self._attr_translation_key = key
        self._attr_unique_id = f"{data.vin}-{key}"
        self._attr_device_info = data.device

    @override
    async def async_added_to_hass(self) -> None:
        """Seed from the funnel's current value and subscribe to changes."""
        self._value = self.funnel.value(self._field)
        self._render_value()
        self.async_on_remove(self.funnel.listen(self._field, self._handle_value))

    @callback
    def _handle_value(self, value: bool | None) -> None:
        """Store a freshly funnelled value and re-render."""
        self._value = value
        self._render_value()
        self.async_write_ha_state()

    def _render_value(self) -> None:
        """Render the current value into entity attributes."""

    @property
    @override
    def available(self) -> bool:
        """Return True only while the funnel holds a value for the field."""
        return self._value is not None
