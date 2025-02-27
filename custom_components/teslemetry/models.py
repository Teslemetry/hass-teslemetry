"""The Teslemetry integration models."""

from __future__ import annotations
from collections.abc import Callable
from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util
from tesla_fleet_api import Teslemetry
import asyncio
from dataclasses import dataclass

from tesla_fleet_api.teslemetry.vehicles import TeslemetryVehicleFleet
from tesla_fleet_api.tesla.energysite import EnergySite
from tesla_fleet_api.const import Scope

from teslemetry_stream import TeslemetryStream, TeslemetryStreamVehicle

from homeassistant.helpers.device_registry import DeviceInfo

from .coordinator import (
    TeslemetryEnergySiteInfoCoordinator,
    TeslemetryEnergySiteLiveCoordinator,
    TeslemetryEnergyHistoryCoordinator,
    TeslemetryVehicleDataCoordinator,
)

@dataclass
class TeslemetryData:
    """Data for the Teslemetry integration."""

    vehicles: list[TeslemetryVehicleData]
    energysites: list[TeslemetryEnergyData]
    scopes: list[Scope]
    teslemetry: Teslemetry
    stream: TeslemetryStream


@dataclass
class TeslemetryVehicleData:
    """Data for a vehicle in the Teslemetry integration."""

    api: TeslemetryVehicleFleet
    config_entry: ConfigEntry
    coordinator: TeslemetryVehicleDataCoordinator
    stream: TeslemetryStream
    stream_vehicle: TeslemetryStreamVehicle
    vin: str
    firmware: str
    device: DeviceInfo
    remove_listener: Callable
    wakelock = asyncio.Lock()
    last_alert: str = dt_util.utcnow().isoformat()
    last_error: str = dt_util.utcnow().isoformat()



@dataclass
class TeslemetryEnergyData:
    """Data for a vehicle in the Teslemetry integration."""

    api: EnergySite
    live_coordinator: TeslemetryEnergySiteLiveCoordinator
    info_coordinator: TeslemetryEnergySiteInfoCoordinator
    id: int
    device: DeviceInfo
    history_coordinator: TeslemetryEnergyHistoryCoordinator | None = None
