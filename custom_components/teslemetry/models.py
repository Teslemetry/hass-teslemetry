"""The Teslemetry integration models."""

from __future__ import annotations
from homeassistant.util import dt as dt_util

import asyncio
from dataclasses import dataclass

from tesla_fleet_api import EnergySpecific, VehicleSpecific
from tesla_fleet_api.const import Scope

from teslemetry_stream import TeslemetryStream

from homeassistant.helpers.device_registry import DeviceInfo

from .coordinator import (
    TeslemetryEnergySiteInfoCoordinator,
    TeslemetryEnergySiteLiveCoordinator,
    TeslemetryVehicleDataCoordinator,
)


@dataclass
class TeslemetryData:
    """Data for the Teslemetry integration."""

    vehicles: list[TeslemetryVehicleData]
    energysites: list[TeslemetryEnergyData]
    scopes: list[Scope]


@dataclass
class TeslemetryVehicleData:
    """Data for a vehicle in the Teslemetry integration."""

    api: VehicleSpecific
    coordinator: TeslemetryVehicleDataCoordinator
    stream: TeslemetryStream
    remove_listeners: tuple[callable]
    vin: str
    device: DeviceInfo
    wakelock = asyncio.Lock()
    last_alert: str = dt_util.utcnow().isoformat()
    last_error: str = dt_util.utcnow().isoformat()


@dataclass
class TeslemetryEnergyData:
    """Data for a vehicle in the Teslemetry integration."""

    api: EnergySpecific
    live_coordinator: TeslemetryEnergySiteLiveCoordinator
    info_coordinator: TeslemetryEnergySiteInfoCoordinator
    id: int
    device: DeviceInfo
