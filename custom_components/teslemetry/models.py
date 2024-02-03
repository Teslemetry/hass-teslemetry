"""The Teslemetry integration models."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from tesla_fleet_api import EnergySpecific, VehicleSpecific
from tesla_fleet_api.const import Scopes

from .coordinator import (
    TeslemetryEnergySiteLiveCoordinator,
    TeslemetryVehicleDataCoordinator,
    TeslemetryEnergySiteInfoCoordinator
)


@dataclass
class TeslemetryData:
    """Data for the Teslemetry integration."""

    vehicles: list[TeslemetryVehicleData]
    energysites: list[TeslemetryEnergyData]
    scopes: list[Scopes]


@dataclass
class TeslemetryVehicleData:
    """Data for a vehicle in the Teslemetry integration."""

    api: VehicleSpecific
    coordinator: TeslemetryVehicleDataCoordinator
    vin: str
    wakelock = asyncio.Lock()


@dataclass
class TeslemetryEnergyData:
    """Data for a vehicle in the Teslemetry integration."""

    api: EnergySpecific
    live_coordinator: TeslemetryEnergySiteLiveCoordinator
    info_coordinator: TeslemetryEnergySiteInfoCoordinator
    id: int
