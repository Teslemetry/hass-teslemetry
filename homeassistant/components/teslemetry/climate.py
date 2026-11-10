"""Climate platform for Teslemetry integration."""

from abc import abstractmethod
from itertools import chain
from typing import TYPE_CHECKING, Any, cast, override

from tesla_fleet_api import firmware_at_least
from tesla_fleet_api.const import CabinOverheatProtectionTemp, Scope
from tesla_fleet_api.router import VehicleRouter
from tesla_fleet_api.teslemetry import Vehicle

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    HVAC_MODES,
    ClimateEntity,
    ClimateEntityFeature,
    ClimateEntityStateAttribute,
    HVACMode,
    RestoreClimate,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    PRECISION_HALVES,
    PRECISION_WHOLE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TeslemetryConfigEntry
from .const import DOMAIN, TeslemetryClimateSide
from .entity import (
    TeslemetryRootEntity,
    TeslemetryVehiclePollingEntity,
    TeslemetryVehicleStreamEntity,
)
from .helpers import handle_vehicle_command
from .models import TeslemetryVehicleData

DEFAULT_MIN_TEMP = 15
DEFAULT_MAX_TEMP = 28
COP_TEMPERATURES = {
    30: CabinOverheatProtectionTemp.LOW,
    35: CabinOverheatProtectionTemp.MEDIUM,
    40: CabinOverheatProtectionTemp.HIGH,
}
PRESET_MODES = {
    "Off": "off",
    "On": "keep",
    "Dog": "dog",
    "Party": "camp",
}
POLLING_PRESET_MODES = {
    "off": "off",
    "on": "keep",
    "dog": "dog",
    "camp": "camp",
}
PRESET_SYNC = "sync"
PRESET_SPLIT = "split"
PASSENGER_FEATURES = (
    ClimateEntityFeature.TURN_ON
    | ClimateEntityFeature.TURN_OFF
    | ClimateEntityFeature.PRESET_MODE
)


PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Teslemetry Climate platform from a config entry."""

    # Streaming vehicles are never polled, so their vehicle_config comes from metadata
    vehicles_metadata = entry.runtime_data.metadata_coordinator.data["vehicles"]
    async_add_entities(
        chain(
            (
                TeslemetryVehiclePollingClimateEntity(
                    vehicle, TeslemetryClimateSide.DRIVER, entry.runtime_data.scopes
                )
                if vehicle.poll or not firmware_at_least(vehicle.firmware, "2024.44.25")
                else TeslemetryStreamingClimateEntity(
                    vehicle,
                    TeslemetryClimateSide.DRIVER,
                    entry.runtime_data.scopes,
                    vehicles_metadata[vehicle.vin].get("config", {}).get("rhd", False),
                )
                for vehicle in entry.runtime_data.vehicles
            ),
            (
                TeslemetryVehiclePollingPassengerClimateEntity(
                    vehicle, TeslemetryClimateSide.PASSENGER, entry.runtime_data.scopes
                )
                if vehicle.poll or not firmware_at_least(vehicle.firmware, "2024.44.25")
                else TeslemetryStreamingPassengerClimateEntity(
                    vehicle,
                    TeslemetryClimateSide.PASSENGER,
                    entry.runtime_data.scopes,
                    vehicles_metadata[vehicle.vin].get("config", {}).get("rhd", False),
                )
                for vehicle in entry.runtime_data.vehicles
            ),
            (
                TeslemetryVehiclePollingCabinOverheatProtectionEntity(
                    vehicle, entry.runtime_data.scopes
                )
                if vehicle.poll or not firmware_at_least(vehicle.firmware, "2024.44.25")
                else TeslemetryStreamingCabinOverheatProtectionEntity(
                    vehicle,
                    entry.runtime_data.scopes,
                    bool(
                        vehicles_metadata[vehicle.vin]
                        .get("config", {})
                        .get("cop_user_set_temp_supported")
                    ),
                )
                for vehicle in entry.runtime_data.vehicles
            ),
        )
    )


class TeslemetryCabinClimateEntity(TeslemetryRootEntity, ClimateEntity):
    """Vehicle cabin climate control for one front seat."""

    api: Vehicle | VehicleRouter
    _attr_precision = PRECISION_HALVES
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT_COOL, HVACMode.OFF]

    @override
    async def async_turn_on(self) -> None:
        """Set the climate state to on."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await handle_vehicle_command(self.api.auto_conditioning_start())

        self._attr_hvac_mode = HVACMode.HEAT_COOL
        self.async_write_ha_state()

    @override
    async def async_turn_off(self) -> None:
        """Set the climate state to off."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await handle_vehicle_command(self.api.auto_conditioning_stop())

        self._attr_hvac_mode = HVACMode.OFF
        self.async_write_ha_state()

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the climate mode and state."""
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
        else:
            await self.async_turn_on()


class TeslemetryClimateEntity(TeslemetryCabinClimateEntity):
    """Vehicle Climate Control."""

    _attr_preset_modes = list(PRESET_MODES.values())
    _attr_fan_modes = ["off", "bioweapon"]
    _native_passenger_temperature: float | None = None

    @override
    async def async_turn_off(self) -> None:
        """Set the climate state to off."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await handle_vehicle_command(self.api.auto_conditioning_stop())

        self._attr_hvac_mode = HVACMode.OFF
        self._attr_preset_mode = self._attr_preset_modes[0]
        self._attr_fan_mode = self._attr_fan_modes[0]
        self.async_write_ha_state()

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the climate temperature."""

        if temp := kwargs.get(ATTR_TEMPERATURE):
            self.raise_for_scope(Scope.VEHICLE_CMDS)

            # A passenger set point that differs from the driver's is split, so keep it
            passenger_temp = self._native_passenger_temperature
            if (
                passenger_temp is None
                or passenger_temp == self._attr_native_target_temperature
            ):
                passenger_temp = temp

            await handle_vehicle_command(
                self.api.set_temps(
                    driver_temp=temp,
                    passenger_temp=passenger_temp,
                )
            )
            self._attr_native_target_temperature = temp

        if mode := kwargs.get(ATTR_HVAC_MODE):
            # Set HVAC mode will call write_ha_state
            await self.async_set_hvac_mode(mode)
        else:
            self.async_write_ha_state()

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the climate preset mode."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await handle_vehicle_command(
            self.api.set_climate_keeper_mode(
                climate_keeper_mode=self._attr_preset_modes.index(preset_mode)
            )
        )
        self._attr_preset_mode = preset_mode
        if preset_mode == self._attr_preset_modes[0]:
            self._attr_hvac_mode = HVACMode.OFF
        else:
            self._attr_hvac_mode = HVACMode.HEAT_COOL
        self.async_write_ha_state()

    @override
    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the Bioweapon defense mode."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await handle_vehicle_command(
            self.api.set_bioweapon_mode(
                on=(fan_mode != "off"),
                manual_override=True,
            )
        )
        self._attr_fan_mode = fan_mode
        if fan_mode == self._attr_fan_modes[1]:
            self._attr_hvac_mode = HVACMode.HEAT_COOL
        self.async_write_ha_state()


class TeslemetryPassengerClimateEntity(TeslemetryCabinClimateEntity):
    """Vehicle passenger climate control, synced with the driver or split."""

    _attr_preset_modes = [PRESET_SYNC, PRESET_SPLIT]
    _attr_entity_registry_enabled_default = False
    _native_driver_temperature: float | None = None

    def _async_configure_preset(self, preset_mode: str | None) -> None:
        """Set the preset, allowing a target temperature only when split."""
        self._attr_preset_mode = preset_mode
        if not self.scoped:
            self._attr_supported_features = ClimateEntityFeature(0)
        elif preset_mode == PRESET_SPLIT:
            self._attr_supported_features = (
                PASSENGER_FEATURES | ClimateEntityFeature.TARGET_TEMPERATURE
            )
        else:
            self._attr_supported_features = PASSENGER_FEATURES

    def _async_update_preset(self) -> None:
        """Derive the preset from the set points, as the vehicle reports no sync state."""
        driver_temp = self._native_driver_temperature
        passenger_temp = self._attr_native_target_temperature
        if driver_temp is None or passenger_temp is None:
            self._async_configure_preset(None)
        elif driver_temp == passenger_temp:
            self._async_configure_preset(PRESET_SYNC)
        else:
            self._async_configure_preset(PRESET_SPLIT)

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the passenger temperature, keeping the driver temperature."""

        if temp := kwargs.get(ATTR_TEMPERATURE):
            self.raise_for_scope(Scope.VEHICLE_CMDS)
            if TYPE_CHECKING:
                # Only split allows a target temperature, and split needs the driver set point
                assert self._native_driver_temperature is not None

            await handle_vehicle_command(
                self.api.set_temps(
                    driver_temp=self._native_driver_temperature,
                    passenger_temp=temp,
                )
            )
            self._attr_native_target_temperature = temp
            self._async_update_preset()

        if mode := kwargs.get(ATTR_HVAC_MODE):
            # Set HVAC mode will call write_ha_state
            await self.async_set_hvac_mode(mode)
        else:
            self.async_write_ha_state()

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Sync the passenger with the driver, or allow a split temperature."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        if (driver_temp := self._native_driver_temperature) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="driver_temperature_unknown",
            )

        if preset_mode == PRESET_SYNC:
            await handle_vehicle_command(
                self.api.set_temps(
                    driver_temp=driver_temp,
                    passenger_temp=driver_temp,
                )
            )
            self._attr_native_target_temperature = driver_temp

        self._async_configure_preset(preset_mode)
        self.async_write_ha_state()


class TeslemetryVehiclePollingCabinClimateEntity(
    TeslemetryCabinClimateEntity, TeslemetryVehiclePollingEntity
):
    """Polling vehicle cabin climate entity."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        side: TeslemetryClimateSide,
        scopes: list[Scope],
    ) -> None:
        """Initialize the climate."""
        self.scoped = Scope.VEHICLE_CMDS in scopes
        super().__init__(data, side)

    @override
    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""
        value = self.get("climate_state_is_climate_on")
        if value is None:
            self._attr_hvac_mode = None
        elif value:
            self._attr_hvac_mode = HVACMode.HEAT_COOL
        else:
            self._attr_hvac_mode = HVACMode.OFF

        self._attr_native_current_temperature = self.get("climate_state_inside_temp")
        self._attr_native_target_temperature = self.get(
            f"climate_state_{self.key}_setting"
        )
        self._attr_min_temp = cast(
            float, self.get("climate_state_min_avail_temp", DEFAULT_MIN_TEMP)
        )
        self._attr_max_temp = cast(
            float, self.get("climate_state_max_avail_temp", DEFAULT_MAX_TEMP)
        )


class TeslemetryVehiclePollingClimateEntity(
    TeslemetryClimateEntity, TeslemetryVehiclePollingCabinClimateEntity
):
    """Polling vehicle climate entity."""

    _attr_supported_features = (
        ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.FAN_MODE
    )

    def __init__(
        self,
        data: TeslemetryVehicleData,
        side: TeslemetryClimateSide,
        scopes: list[Scope],
    ) -> None:
        """Initialize the climate."""
        super().__init__(data, side, scopes)
        if not self.scoped:
            self._attr_supported_features = ClimateEntityFeature(0)

    @override
    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""
        super()._async_update_attrs()
        keeper_mode = self.get("climate_state_climate_keeper_mode")
        self._attr_preset_mode = (
            POLLING_PRESET_MODES.get(keeper_mode) if keeper_mode else None
        )
        if self.get("climate_state_bioweapon_mode"):
            self._attr_fan_mode = "bioweapon"
        else:
            self._attr_fan_mode = "off"
        self._native_passenger_temperature = self.get(
            "climate_state_passenger_temp_setting"
        )


class TeslemetryVehiclePollingPassengerClimateEntity(
    TeslemetryPassengerClimateEntity, TeslemetryVehiclePollingCabinClimateEntity
):
    """Polling vehicle passenger climate entity."""

    @override
    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""
        super()._async_update_attrs()
        self._native_driver_temperature = self.get("climate_state_driver_temp_setting")
        self._async_update_preset()


class TeslemetryStreamingCabinClimateEntity(
    TeslemetryCabinClimateEntity, TeslemetryVehicleStreamEntity, RestoreClimate
):
    """Streaming vehicle cabin climate entity."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        side: TeslemetryClimateSide,
        scopes: list[Scope],
        rhd: bool,
    ) -> None:
        """Initialize the climate."""

        # Initialize defaults
        self._attr_hvac_mode = None
        self._attr_native_current_temperature = None
        self._attr_native_target_temperature = None
        self._attr_fan_mode = None
        self._attr_preset_mode = None

        self.scoped = Scope.VEHICLE_CMDS in scopes
        super().__init__(
            data,
            side,
        )

        self._attr_min_temp = cast(
            float,
            data.coordinator.data.get("climate_state_min_avail_temp", DEFAULT_MIN_TEMP),
        )
        self._attr_max_temp = cast(
            float,
            data.coordinator.data.get("climate_state_max_avail_temp", DEFAULT_MAX_TEMP),
        )
        self.rhd = rhd

    @override
    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            self._attr_hvac_mode = (
                HVACMode(state.state) if state.state in HVAC_MODES else None
            )
        if (climate_data := await self.async_get_last_climate_data()) is not None:
            self._attr_native_current_temperature = (
                climate_data.native_current_temperature
            )
            self._attr_native_target_temperature = (
                climate_data.native_target_temperature
            )

        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_InsideTemp(
                self._async_handle_inside_temp
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_HvacPower(self._async_handle_hvac_power)
        )

        # The stream reports set points by side of the vehicle, not by seat
        if self.rhd:
            listen_driver = (
                self.vehicle.stream_vehicle.listen_HvacRightTemperatureRequest
            )
            listen_passenger = (
                self.vehicle.stream_vehicle.listen_HvacLeftTemperatureRequest
            )
        else:
            listen_driver = (
                self.vehicle.stream_vehicle.listen_HvacLeftTemperatureRequest
            )
            listen_passenger = (
                self.vehicle.stream_vehicle.listen_HvacRightTemperatureRequest
            )
        self.async_on_remove(listen_driver(self._async_handle_driver_temperature))
        self.async_on_remove(listen_passenger(self._async_handle_passenger_temperature))

    def _async_handle_inside_temp(self, data: float | None) -> None:
        self._attr_native_current_temperature = data
        self.async_write_ha_state()

    def _async_handle_hvac_power(self, data: str | None) -> None:
        self._attr_hvac_mode = (
            None
            if data is None
            else HVACMode.HEAT_COOL
            if data in {"On", "Precondition"}
            else HVACMode.OFF
        )
        self.async_write_ha_state()

    @abstractmethod
    def _async_handle_driver_temperature(self, data: float | None) -> None:
        """Handle the driver set point."""

    @abstractmethod
    def _async_handle_passenger_temperature(self, data: float | None) -> None:
        """Handle the passenger set point."""


class TeslemetryStreamingClimateEntity(
    TeslemetryClimateEntity, TeslemetryStreamingCabinClimateEntity
):
    """Teslemetry steering wheel climate control."""

    _attr_supported_features = (
        ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
    )

    def __init__(
        self,
        data: TeslemetryVehicleData,
        side: TeslemetryClimateSide,
        scopes: list[Scope],
        rhd: bool,
    ) -> None:
        """Initialize the climate."""
        super().__init__(data, side, scopes, rhd)
        if not self.scoped:
            self._attr_supported_features = ClimateEntityFeature(0)

    @override
    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            self._attr_preset_mode = state.attributes.get(
                ClimateEntityStateAttribute.PRESET_MODE
            )

        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_ClimateKeeperMode(
                self._async_handle_climate_keeper_mode
            )
        )

    def _async_handle_climate_keeper_mode(self, data: str | None) -> None:
        self._attr_preset_mode = PRESET_MODES.get(data) if data else None
        self.async_write_ha_state()

    @override
    def _async_handle_driver_temperature(self, data: float | None) -> None:
        self._attr_native_target_temperature = data
        self.async_write_ha_state()

    @override
    def _async_handle_passenger_temperature(self, data: float | None) -> None:
        self._native_passenger_temperature = data


class TeslemetryStreamingPassengerClimateEntity(
    TeslemetryPassengerClimateEntity, TeslemetryStreamingCabinClimateEntity
):
    """Teslemetry passenger climate control."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        side: TeslemetryClimateSide,
        scopes: list[Scope],
        rhd: bool,
    ) -> None:
        """Initialize the climate."""
        super().__init__(data, side, scopes, rhd)
        self._async_update_preset()

    @override
    def _async_handle_driver_temperature(self, data: float | None) -> None:
        self._native_driver_temperature = data
        self._async_update_preset()
        self.async_write_ha_state()

    @override
    def _async_handle_passenger_temperature(self, data: float | None) -> None:
        self._attr_native_target_temperature = data
        self._async_update_preset()
        self.async_write_ha_state()


COP_MODES = {
    "Off": HVACMode.OFF,
    "On": HVACMode.COOL,
    "FanOnly": HVACMode.FAN_ONLY,
}

COP_LEVELS = {
    "Low": 30,
    "Medium": 35,
    "High": 40,
}


class TeslemetryCabinOverheatProtectionEntity(TeslemetryRootEntity, ClimateEntity):
    """Vehicle Cabin Overheat Protection."""

    api: Vehicle | VehicleRouter
    _attr_precision = PRECISION_WHOLE
    _attr_target_temperature_step = 5
    _attr_min_temp = 30
    _attr_max_temp = 40
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = list(COP_MODES.values())
    _attr_entity_registry_enabled_default = False

    _enable_turn_on_off_backwards_compatibility = False

    @override
    async def async_turn_on(self) -> None:
        """Set the climate state to on."""
        await self.async_set_hvac_mode(HVACMode.COOL)

    @override
    async def async_turn_off(self) -> None:
        """Set the climate state to off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the climate temperature."""

        if temp := kwargs.get(ATTR_TEMPERATURE):
            # Temperatures converted from Fahrenheit rarely hit a level exactly
            level = min(COP_TEMPERATURES, key=lambda t: abs(t - temp))
            self.raise_for_scope(Scope.VEHICLE_CMDS)

            await handle_vehicle_command(self.api.set_cop_temp(COP_TEMPERATURES[level]))
            self._attr_native_target_temperature = level

        if mode := kwargs.get(ATTR_HVAC_MODE):
            # Set HVAC mode will call write_ha_state
            await self.async_set_hvac_mode(mode)
        else:
            self.async_write_ha_state()

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the climate mode and state."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        if hvac_mode == HVACMode.OFF:
            await handle_vehicle_command(
                self.api.set_cabin_overheat_protection(on=False, fan_only=False)
            )
        elif hvac_mode == HVACMode.COOL:
            await handle_vehicle_command(
                self.api.set_cabin_overheat_protection(on=True, fan_only=False)
            )
        elif hvac_mode == HVACMode.FAN_ONLY:
            await handle_vehicle_command(
                self.api.set_cabin_overheat_protection(on=True, fan_only=True)
            )

        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()


class TeslemetryVehiclePollingCabinOverheatProtectionEntity(
    TeslemetryVehiclePollingEntity, TeslemetryCabinOverheatProtectionEntity
):
    """Vehicle Cabin Overheat Protection."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the climate."""

        super().__init__(
            data,
            "climate_state_cabin_overheat_protection",
        )

        # Supported Features
        self._attr_supported_features = (
            ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        )
        if self.get("vehicle_config_cop_user_set_temp_supported"):
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE

        # Scopes
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = ClimateEntityFeature(0)

    @override
    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""

        if (state := self.get("climate_state_cabin_overheat_protection")) is None:
            self._attr_hvac_mode = None
        else:
            self._attr_hvac_mode = COP_MODES.get(state)

        if (level := self.get("climate_state_cop_activation_temperature")) is None:
            self._attr_native_target_temperature = None
        else:
            self._attr_native_target_temperature = COP_LEVELS.get(level)

        self._attr_native_current_temperature = self.get("climate_state_inside_temp")


class TeslemetryStreamingCabinOverheatProtectionEntity(
    TeslemetryVehicleStreamEntity,
    TeslemetryCabinOverheatProtectionEntity,
    RestoreClimate,
):
    """Vehicle Cabin Overheat Protection."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scopes: list[Scope],
        cop_temp_supported: bool,
    ) -> None:
        """Initialize the climate."""

        # Initialize defaults
        self._attr_hvac_mode = None
        self._attr_native_current_temperature = None
        self._attr_native_target_temperature = None
        self._attr_fan_mode = None
        self._attr_preset_mode = None

        super().__init__(data, "climate_state_cabin_overheat_protection")

        # Supported Features
        self._attr_supported_features = (
            ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        )
        if cop_temp_supported:
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE

        # Scopes
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = ClimateEntityFeature(0)

    @override
    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            self._attr_hvac_mode = (
                HVACMode(state.state) if state.state in HVAC_MODES else None
            )
        if (climate_data := await self.async_get_last_climate_data()) is not None:
            self._attr_native_current_temperature = (
                climate_data.native_current_temperature
            )
            self._attr_native_target_temperature = (
                climate_data.native_target_temperature
            )

        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_InsideTemp(
                self._async_handle_inside_temp
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_CabinOverheatProtectionMode(
                self._async_handle_protection_mode
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_CabinOverheatProtectionTemperatureLimit(
                self._async_handle_temperature_limit
            )
        )

    def _async_handle_inside_temp(self, value: float | None) -> None:
        self._attr_native_current_temperature = value
        self.async_write_ha_state()

    def _async_handle_protection_mode(self, value: str | None) -> None:
        self._attr_hvac_mode = COP_MODES.get(value) if value is not None else None
        self.async_write_ha_state()

    def _async_handle_temperature_limit(self, value: str | None) -> None:
        self._attr_native_target_temperature = (
            COP_LEVELS.get(value) if value is not None else None
        )
        self.async_write_ha_state()
