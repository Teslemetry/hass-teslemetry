"""Test the Teslemetry number platform."""

import asyncio
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import async_fire_time_changed
from syrupy.assertion import SnapshotAssertion
from tesla_fleet_api.exceptions import InvalidCommand
from teslemetry_stream import Signal

from homeassistant.components.labs import async_update_preview_feature
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN, SERVICE_TURN_ON
from homeassistant.components.teslemetry.const import (
    DOMAIN,
    LABS_CHARGE_ON_SOLAR_FEATURE,
)
from homeassistant.components.teslemetry.coordinator import (
    ENERGY_CONFIG_INTERVAL,
    METADATA_INTERVAL,
)
from homeassistant.components.teslemetry.number import (
    TeslemetryChargeOnSolarLowerLimitNumberEntity,
)
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from . import (
    assert_entities,
    mock_config_entry,
    refresh_entity,
    reload_platform,
    setup_paired_platform,
    setup_platform,
)
from .const import (
    COMMAND_ERRORS,
    COMMAND_OK,
    CONFIG_JSON_APPLIED,
    CONFIG_JSON_NOT_APPLIED,
    METADATA,
    METADATA_NOSCOPE,
    SITE_INFO,
    VEHICLE_DATA,
    VEHICLE_DATA_ALT,
    VIN,
)


async def _async_enable_charge_on_solar_preview_feature(hass: HomeAssistant) -> None:
    """Enable the Teslemetry charge-on-solar preview feature."""
    assert await async_setup_component(hass, "labs", {})
    await async_update_preview_feature(hass, DOMAIN, LABS_CHARGE_ON_SOLAR_FEATURE, True)


SITE_ID = 123456
GRID_LIMIT_ENTITY_IDS = (
    "number.energy_site_grid_export_limit",
    "number.energy_site_grid_import_limit",
    "switch.energy_site_solar_curtailment",
)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_number(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the number entities are correct."""

    entry = await setup_platform(hass, [Platform.NUMBER])
    assert_entities(hass, entry.entry_id, entity_registry, snapshot)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_number_services(
    hass: HomeAssistant, mock_vehicle_data: AsyncMock
) -> None:
    """Tests that the number services work."""
    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    await setup_platform(hass, [Platform.NUMBER])

    entity_id = "number.test_charge_current"
    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.set_charging_amps",
        return_value=COMMAND_OK,
    ) as call:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: 16},
            blocking=True,
        )
        state = hass.states.get(entity_id)
        assert state.state == "16"
        call.assert_called_once()

    entity_id = "number.test_charge_limit"
    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.set_charge_limit",
        return_value=COMMAND_OK,
    ) as call:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: 60},
            blocking=True,
        )
        state = hass.states.get(entity_id)
        assert state.state == "60"
        call.assert_called_once()

    entity_id = "number.energy_site_backup_reserve"
    with patch(
        "tesla_fleet_api.teslemetry.EnergySite.backup",
        return_value=COMMAND_OK,
    ) as call:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {
                ATTR_ENTITY_ID: entity_id,
                ATTR_VALUE: 80,
            },
            blocking=True,
        )
        state = hass.states.get(entity_id)
        assert state.state == "80"
        call.assert_called_once()

    entity_id = "number.energy_site_off_grid_reserve"
    with patch(
        "tesla_fleet_api.teslemetry.EnergySite.off_grid_vehicle_charging_reserve",
        return_value=COMMAND_OK,
    ) as call:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: 88},
            blocking=True,
        )
        state = hass.states.get(entity_id)
        assert state.state == "88"
        call.assert_called_once()


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize("response", COMMAND_ERRORS)
async def test_number_command_errors(
    hass: HomeAssistant, mock_vehicle_data: AsyncMock, response: dict
) -> None:
    """Tests that vehicle command failures raise HomeAssistantError."""
    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    await setup_platform(hass, [Platform.NUMBER])

    with (
        patch(
            "tesla_fleet_api.teslemetry.Vehicle.set_charging_amps",
            return_value=response,
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_current", ATTR_VALUE: 16},
            blocking=True,
        )


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_number_command_exception(hass: HomeAssistant) -> None:
    """Tests that an energy command SDK exception raises HomeAssistantError."""
    await setup_platform(hass, [Platform.NUMBER])

    with (
        patch(
            "tesla_fleet_api.teslemetry.EnergySite.backup",
            side_effect=InvalidCommand,
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.energy_site_backup_reserve", ATTR_VALUE: 80},
            blocking=True,
        )


async def test_number_streaming(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
) -> None:
    """Tests that the number entities with streaming are correct."""

    entry = await setup_platform(hass, [Platform.NUMBER])

    # Stream update
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.CHARGE_CURRENT_REQUEST: 24,
                Signal.CHARGE_CURRENT_REQUEST_MAX: 32,
                Signal.CHARGE_LIMIT_SOC: 99,
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    await reload_platform(hass, entry, [Platform.NUMBER])

    # Assert the entities restored their values with concrete assertions
    assert hass.states.get("number.test_charge_current").state == "24"
    assert hass.states.get("number.test_charge_limit").state == "99"


async def test_charge_on_solar_lower_limit_disabled_by_default(
    hass: HomeAssistant,
) -> None:
    """Test charge-on-solar lower limit is disabled by default."""
    await setup_platform(hass, [Platform.NUMBER])

    assert hass.states.get("number.test_charge_on_solar_lower_limit") is None


async def test_charge_on_solar_lower_limit_enabled_by_labs(
    hass: HomeAssistant,
) -> None:
    """Test charge-on-solar lower limit appears when Labs feature is enabled."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    await setup_platform(hass, [Platform.NUMBER])

    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.state == "20"
    assert state.attributes["assumed_state"] is True


async def test_charge_on_solar_lower_limit_capped_by_charge_limit(
    hass: HomeAssistant,
) -> None:
    """Test the lower limit's max value tracks the current charge limit SOC."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch(
        "teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc"
    ) as listener:
        listener.return_value = lambda: None
        await setup_platform(hass, [Platform.NUMBER])

        for call in listener.call_args_list:
            call.args[0](70)
        await hass.async_block_till_done()

    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.attributes["max"] == 70

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit", ATTR_VALUE: 60},
        blocking=True,
    )

    # A subsequent drop below the stored value clamps it down too
    for call in listener.call_args_list:
        call.args[0](50)
    await hass.async_block_till_done()

    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.attributes["max"] == 50
    assert state.state == "50"


async def test_charge_on_solar_lower_limit_capped_by_charge_limit_polling(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
    mock_legacy: AsyncMock,
) -> None:
    """Test the polling lower limit's max value tracks the coordinator charge limit."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    await setup_platform(hass, [Platform.NUMBER])

    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.attributes["max"] == 80

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit", ATTR_VALUE: 70},
        blocking=True,
    )

    lowered_data = deepcopy(VEHICLE_DATA)
    lowered_data["response"]["charge_state"]["charge_limit_soc"] = 50
    mock_vehicle_data.return_value = lowered_data
    await refresh_entity(hass, "number.test_charge_limit")

    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.attributes["max"] == 50
    assert state.state == "50"


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "mock_old_firmware")
async def test_charge_on_solar_lower_limit_old_firmware_follows_polled_charge_limit(
    hass: HomeAssistant,
) -> None:
    """Test a stream-only vehicle on pre-streaming firmware is capped by the polled charge limit."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    await setup_platform(hass, [Platform.NUMBER])

    # This vehicle's raw poll flag is off, so its coordinator gets no initial
    # refresh; the linked charge-limit entity has no value yet, so max falls
    # back to its default.
    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.attributes["max"] == 100

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit", ATTR_VALUE: 90},
            blocking=True,
        )

    await refresh_entity(hass, "number.test_charge_limit")

    assert hass.states.get("number.test_charge_limit").state == "80"
    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.attributes["max"] == 80
    assert state.state == "80"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit", ATTR_VALUE: 90},
            blocking=True,
        )


async def test_charge_on_solar_lower_limit_restores_max_value(
    hass: HomeAssistant,
) -> None:
    """Test the lower limit's max value survives a reload without new telemetry."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch(
        "teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc"
    ) as listener:
        listener.return_value = lambda: None
        entry = await setup_platform(hass, [Platform.NUMBER])

        for call in listener.call_args_list:
            call.args[0](70)
        await hass.async_block_till_done()

    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.attributes["max"] == 70

    with patch(
        "teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc",
        return_value=lambda: None,
    ):
        await reload_platform(hass, entry, [Platform.NUMBER])

    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.attributes["max"] == 70


async def test_charge_on_solar_lower_limit_set_value_while_disabled(
    hass: HomeAssistant,
) -> None:
    """Test setting the lower limit while charge-on-solar is off updates state only."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    await setup_platform(hass, [Platform.NUMBER])

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ) as command:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit", ATTR_VALUE: 35},
            blocking=True,
        )
        command.assert_not_called()

    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.state == "35"


async def test_charge_on_solar_lower_limit_set_value_while_enabled(
    hass: HomeAssistant,
) -> None:
    """Test setting the lower limit while charge-on-solar is on sends the command."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch(
        "teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc"
    ) as listener:
        listener.return_value = lambda: None
        await setup_platform(hass, [Platform.SWITCH, Platform.NUMBER])

        for call in listener.call_args_list:
            call.args[0](91)
        await hass.async_block_till_done()

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ):
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: "switch.test_charge_on_solar"},
            blocking=True,
        )

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ) as command:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit", ATTR_VALUE: 35},
            blocking=True,
        )
        command.assert_called_once_with(
            enabled=True,
            lower_charge_limit=35,
            upper_charge_limit=91,
        )

    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.state == "35"


async def test_charge_on_solar_lower_limit_reaches_vehicle_when_switch_disabled(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test a number change still reaches the vehicle once the switch entity is registry-disabled."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch(
        "teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc"
    ) as listener:
        listener.return_value = lambda: None
        entry = await setup_platform(hass, [Platform.SWITCH, Platform.NUMBER])

        with patch(
            "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
            return_value=COMMAND_OK,
        ):
            await hass.services.async_call(
                SWITCH_DOMAIN,
                SERVICE_TURN_ON,
                {ATTR_ENTITY_ID: "switch.test_charge_on_solar"},
                blocking=True,
            )

        entity_registry.async_update_entity(
            "switch.test_charge_on_solar",
            disabled_by=er.RegistryEntryDisabler.USER,
        )
        await hass.async_block_till_done()

        await reload_platform(hass, entry, [Platform.SWITCH, Platform.NUMBER])

    assert hass.states.get("switch.test_charge_on_solar") is None

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ) as command:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit", ATTR_VALUE: 45},
            blocking=True,
        )
        command.assert_called_once_with(
            enabled=True,
            lower_charge_limit=45,
            upper_charge_limit=None,
        )


async def test_charge_on_solar_lower_limit_uses_stored_state_when_switch_disabled(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    entity_registry: er.EntityRegistry,
) -> None:
    """Test a number change reaches the vehicle after a restart with the switch long disabled."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    entry = mock_config_entry()
    entry.add_to_hass(hass)
    # No restore state exists for the disabled switch, as once it has expired.
    hass_storage[f"{DOMAIN}.charge_on_solar.{entry.entry_id}"] = {
        "version": 1,
        "data": {VIN: {"enabled": True, "lower_limit": 35, "charge_limit_soc": None}},
    }
    entity_registry.async_get_or_create(
        SWITCH_DOMAIN,
        DOMAIN,
        f"{VIN}-charge_on_solar",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    with patch(
        "homeassistant.components.teslemetry.PLATFORMS",
        [Platform.SWITCH, Platform.NUMBER],
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("switch.test_charge_on_solar") is None
    assert (state := hass.states.get("number.test_charge_on_solar_lower_limit"))
    assert state.state == "35"

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ) as command:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit", ATTR_VALUE: 45},
            blocking=True,
        )
        command.assert_called_once_with(
            enabled=True,
            lower_charge_limit=45,
            upper_charge_limit=None,
        )


async def test_charge_on_solar_lower_limit_uses_live_charge_limit(
    hass: HomeAssistant,
) -> None:
    """Test the lower limit command carries the live charge limit, not a stale cache."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch(
        "teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc"
    ) as listener:
        listener.return_value = lambda: None
        await setup_platform(hass, [Platform.SWITCH, Platform.NUMBER])

        for call in listener.call_args_list:
            call.args[0](91)
        await hass.async_block_till_done()

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ):
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: "switch.test_charge_on_solar"},
            blocking=True,
        )

    # The owner raises the charge limit with no stream or poll update following it.
    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.set_charge_limit",
        return_value=COMMAND_OK,
    ):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_limit", ATTR_VALUE: 95},
            blocking=True,
        )

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ) as command:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit", ATTR_VALUE: 35},
            blocking=True,
        )
        command.assert_called_once_with(
            enabled=True,
            lower_charge_limit=35,
            upper_charge_limit=95,
        )


async def test_charge_on_solar_lower_limit_rejects_stale_max_while_disabled(
    hass: HomeAssistant,
) -> None:
    """Test the lower limit's advertised max tracks a locally lowered charge limit."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    await setup_platform(hass, [Platform.NUMBER])

    # The owner lowers the charge limit locally with no stream or poll update following it.
    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.set_charge_limit",
        return_value=COMMAND_OK,
    ):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_limit", ATTR_VALUE: 50},
            blocking=True,
        )

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit", ATTR_VALUE: 60},
            blocking=True,
        )

    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.state == "20"


async def test_charge_on_solar_switch_and_lower_limit_are_serialized(
    hass: HomeAssistant,
) -> None:
    """Test a concurrent switch turn-on and lower-limit set don't diverge from the vehicle."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch(
        "teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc"
    ) as listener:
        listener.return_value = lambda: None
        await setup_platform(hass, [Platform.SWITCH, Platform.NUMBER])

        for call in listener.call_args_list:
            call.args[0](80)
        await hass.async_block_till_done()

    switch_call_started = asyncio.Event()
    release_switch_call = asyncio.Event()
    lower_limit_reached_lock = asyncio.Event()

    async def slow_charge_on_solar(**kwargs: Any) -> dict[str, Any]:
        switch_call_started.set()
        await release_switch_call.wait()
        return COMMAND_OK

    set_native_value = (
        TeslemetryChargeOnSolarLowerLimitNumberEntity.async_set_native_value
    )

    async def tracked_set_native_value(
        self: TeslemetryChargeOnSolarLowerLimitNumberEntity, value: float
    ) -> None:
        lower_limit_reached_lock.set()
        await set_native_value(self, value)

    with (
        patch(
            "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
            side_effect=slow_charge_on_solar,
        ) as command,
        # The lock is taken first thing in the set, so once it is entered the number
        # either waits on the lock or runs ahead of the switch.
        patch.object(
            TeslemetryChargeOnSolarLowerLimitNumberEntity,
            "async_set_native_value",
            tracked_set_native_value,
        ),
    ):
        turn_on = hass.async_create_task(
            hass.services.async_call(
                SWITCH_DOMAIN,
                SERVICE_TURN_ON,
                {ATTR_ENTITY_ID: "switch.test_charge_on_solar"},
                blocking=True,
            ),
            "test turn on charge-on-solar",
        )
        await switch_call_started.wait()

        set_lower_limit = hass.async_create_task(
            hass.services.async_call(
                NUMBER_DOMAIN,
                SERVICE_SET_VALUE,
                {
                    ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit",
                    ATTR_VALUE: 35,
                },
                blocking=True,
            ),
            "test set charge-on-solar lower limit",
        )

        await lower_limit_reached_lock.wait()
        assert command.call_count == 1

        release_switch_call.set()
        await turn_on
        await set_lower_limit

        assert command.call_count == 2
        command.assert_called_with(
            enabled=True,
            lower_charge_limit=35,
            upper_charge_limit=80,
        )

    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.state == "35"


async def test_charge_on_solar_lower_limit_set_value_command_failure(
    hass: HomeAssistant,
) -> None:
    """Test a failed command leaves the previous value intact, not the optimistic one."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch(
        "teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc"
    ) as listener:
        listener.return_value = lambda: None
        await setup_platform(hass, [Platform.SWITCH, Platform.NUMBER])

        for call in listener.call_args_list:
            call.args[0](91)
        await hass.async_block_till_done()

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ):
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: "switch.test_charge_on_solar"},
            blocking=True,
        )

    with (
        patch(
            "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
            side_effect=InvalidCommand,
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit", ATTR_VALUE: 35},
            blocking=True,
        )

    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.state == "20"


async def test_disable_charge_on_solar_preview_removes_lower_limit(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test disabling preview removes the lower limit from entity registry."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    entry = await setup_platform(hass, [Platform.NUMBER])

    assert (
        entity_registry.async_get("number.test_charge_on_solar_lower_limit") is not None
    )

    with patch.object(hass.config_entries, "async_schedule_reload"):
        await async_update_preview_feature(
            hass, DOMAIN, LABS_CHARGE_ON_SOLAR_FEATURE, False
        )
        await hass.async_block_till_done()

    await reload_platform(hass, entry, [Platform.NUMBER])

    assert entity_registry.async_get("number.test_charge_on_solar_lower_limit") is None


async def test_charge_on_solar_lower_limit_removed_without_command_scope(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_metadata: MagicMock,
) -> None:
    """Test the lower limit is removed when the vehicle commands scope is revoked."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    entry = await setup_platform(hass, [Platform.NUMBER])

    assert (
        entity_registry.async_get("number.test_charge_on_solar_lower_limit") is not None
    )

    mock_metadata.return_value = METADATA_NOSCOPE
    await reload_platform(hass, entry, [Platform.NUMBER])

    assert entity_registry.async_get("number.test_charge_on_solar_lower_limit") is None


@pytest.mark.parametrize(
    "charge_limit_echo",
    [
        pytest.param((90,), id="echoed"),
        pytest.param((), id="not_echoed"),
    ],
)
async def test_charge_on_solar_locally_set_charge_limit_survives_reload(
    hass: HomeAssistant,
    charge_limit_echo: tuple[int, ...],
) -> None:
    """Test a charge limit set from Home Assistant survives a reload, echoed or not."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch(
        "teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc"
    ) as listener:
        listener.return_value = lambda: None
        entry = await setup_platform(hass, [Platform.SWITCH, Platform.NUMBER])
        for call in listener.call_args_list:
            call.args[0](80)
        await hass.async_block_till_done()

        with patch(
            "tesla_fleet_api.teslemetry.Vehicle.set_charge_limit",
            return_value=COMMAND_OK,
        ):
            await hass.services.async_call(
                NUMBER_DOMAIN,
                SERVICE_SET_VALUE,
                {ATTR_ENTITY_ID: "number.test_charge_limit", ATTR_VALUE: 90},
                blocking=True,
            )

        # The vehicle may or may not echo the new limit on the stream before the reload.
        for value in charge_limit_echo:
            for call in listener.call_args_list:
                call.args[0](value)
        await hass.async_block_till_done()

    with patch(
        "teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc",
        return_value=lambda: None,
    ):
        await reload_platform(hass, entry, [Platform.SWITCH, Platform.NUMBER])

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ) as command:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: "switch.test_charge_on_solar"},
            blocking=True,
        )
        command.assert_called_once_with(
            enabled=True,
            lower_charge_limit=20,
            upper_charge_limit=90,
        )


async def test_charge_on_solar_switch_uses_locally_set_charge_limit(
    hass: HomeAssistant,
) -> None:
    """Test the switch sends a charge limit set from Home Assistant as the upper bound."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch(
        "teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc"
    ) as listener:
        listener.return_value = lambda: None
        await setup_platform(hass, [Platform.SWITCH, Platform.NUMBER])

        for call in listener.call_args_list:
            call.args[0](80)
        await hass.async_block_till_done()

    # The owner raises the charge limit with no stream or poll update following it.
    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.set_charge_limit",
        return_value=COMMAND_OK,
    ):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_limit", ATTR_VALUE: 95},
            blocking=True,
        )

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ) as command:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: "switch.test_charge_on_solar"},
            blocking=True,
        )
        command.assert_called_once_with(
            enabled=True,
            lower_charge_limit=20,
            upper_charge_limit=95,
        )


@pytest.mark.usefixtures("mock_legacy")
async def test_charge_on_solar_unknown_polled_charge_limit(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
) -> None:
    """Test a polled vehicle without a charge limit leaves the upper bound unset."""
    vehicle_data = deepcopy(VEHICLE_DATA)
    vehicle_data["response"]["charge_state"]["charge_limit_soc"] = None
    mock_vehicle_data.return_value = vehicle_data
    await _async_enable_charge_on_solar_preview_feature(hass)
    await setup_platform(hass, [Platform.SWITCH, Platform.NUMBER])

    state = hass.states.get("number.test_charge_on_solar_lower_limit")
    assert state is not None
    assert state.attributes["max"] == 100

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ) as command:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: "switch.test_charge_on_solar"},
            blocking=True,
        )
        command.assert_called_once_with(
            enabled=True,
            lower_charge_limit=20,
            upper_charge_limit=None,
        )


@pytest.mark.parametrize(
    ("entity_id", "method", "value", "expected_state"),
    [
        pytest.param(
            "number.energy_site_grid_export_limit",
            "set_export_limit",
            5.5,
            "5.5",
            id="export",
        ),
        pytest.param(
            "number.energy_site_grid_import_limit",
            "set_import_limit",
            14,
            "14.0",
            id="import",
        ),
    ],
)
async def test_grid_limit_number_cloud(
    hass: HomeAssistant,
    entity_id: str,
    method: str,
    value: float,
    expected_state: str,
) -> None:
    """Test a grid limit is sent through Teslemetry for a paired site."""
    await setup_platform(hass, [Platform.NUMBER])

    with patch(
        f"tesla_fleet_api.teslemetry.EnergySite.{method}",
        return_value=CONFIG_JSON_APPLIED,
    ) as call:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
            blocking=True,
        )
    call.assert_awaited_once_with(value)
    assert hass.states.get(entity_id).state == expected_state


async def test_grid_limit_number_value_from_site_info(
    hass: HomeAssistant, mock_site_info: AsyncMock
) -> None:
    """Test the grid limits show the site_info limits as positive kW."""
    site_info = deepcopy(SITE_INFO)
    site_info["response"]["min_site_meter_power_ac"] = -5
    site_info["response"]["max_site_meter_power_ac"] = 14
    mock_site_info.side_effect = None
    mock_site_info.return_value = site_info
    await setup_platform(hass, [Platform.NUMBER])

    assert hass.states.get("number.energy_site_grid_export_limit").state == "5"
    assert hass.states.get("number.energy_site_grid_import_limit").state == "14"


@pytest.mark.parametrize(
    ("subentries", "paired", "created"),
    [
        pytest.param(True, False, True, id="local_only"),
        pytest.param(False, True, True, id="paired_only"),
        pytest.param(True, True, True, id="local_and_paired"),
        pytest.param(False, False, False, id="neither"),
        pytest.param(False, None, False, id="unknown"),
    ],
)
async def test_grid_limit_entities_need_signed_commands(
    hass: HomeAssistant,
    subentries: bool,
    paired: bool | None,
    created: bool,
) -> None:
    """Test grid limit entities exist only when Teslemetry or the local gateway can send them."""
    metadata = deepcopy(METADATA)
    metadata["energy_sites"][str(SITE_ID)]["paired"] = paired
    platforms = [Platform.NUMBER, Platform.SWITCH]
    with patch("tesla_fleet_api.teslemetry.Teslemetry.metadata", return_value=metadata):
        if subentries:
            await setup_paired_platform(hass, platforms)
        else:
            await setup_platform(hass, platforms)

    for entity_id in GRID_LIMIT_ENTITY_IDS:
        assert (hass.states.get(entity_id) is not None) is created


async def test_grid_limit_entities_follow_pairing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Test the entry reloads to add grid limit entities once Teslemetry is paired."""
    metadata = deepcopy(METADATA)
    metadata["energy_sites"][str(SITE_ID)]["paired"] = False
    with patch("tesla_fleet_api.teslemetry.Teslemetry.metadata", return_value=metadata):
        await setup_platform(hass, [Platform.NUMBER, Platform.SWITCH])
    assert hass.states.get("number.energy_site_grid_export_limit") is None

    with patch("homeassistant.components.teslemetry.PLATFORMS", [Platform.NUMBER]):
        freezer.tick(METADATA_INTERVAL)
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get("number.energy_site_grid_export_limit") is not None


GRID_LIMIT_PARAMS = [
    pytest.param(
        "number.energy_site_grid_export_limit", "set_export_limit", 5.0, id="export"
    ),
    pytest.param(
        "number.energy_site_grid_import_limit", "set_import_limit", 14.0, id="import"
    ),
]


@pytest.mark.parametrize(("entity_id", "method", "value"), GRID_LIMIT_PARAMS)
async def test_grid_limit_number_local(
    hass: HomeAssistant, entity_id: str, method: str, value: float
) -> None:
    """Test a grid limit is sent to the local gateway of a site with local control."""
    await setup_paired_platform(hass, [Platform.NUMBER])

    with (
        patch(
            f"tesla_fleet_api.tesla.powerwall.PowerwallEnergySite.{method}",
            return_value=CONFIG_JSON_APPLIED,
        ) as local,
        patch(f"tesla_fleet_api.teslemetry.EnergySite.{method}") as cloud,
    ):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
            blocking=True,
        )
    local.assert_awaited_once_with(value)
    cloud.assert_not_called()
    assert hass.states.get(entity_id).state == str(value)


@pytest.mark.parametrize(("entity_id", "method", "value"), GRID_LIMIT_PARAMS)
async def test_grid_limit_number_not_applied(
    hass: HomeAssistant, entity_id: str, method: str, value: float
) -> None:
    """Test a grid limit the gateway did not keep raises and leaves the state alone."""
    await setup_platform(hass, [Platform.NUMBER])
    before = hass.states.get(entity_id).state

    with (
        patch(
            f"tesla_fleet_api.teslemetry.EnergySite.{method}",
            return_value=CONFIG_JSON_NOT_APPLIED,
        ),
        pytest.raises(HomeAssistantError) as exc_info,
    ):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
            blocking=True,
        )
    assert exc_info.value.translation_key == "config_not_applied"
    assert hass.states.get(entity_id).state == before


async def test_grid_limit_number_value_from_local_config(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_powerwall_local_config: AsyncMock,
) -> None:
    """Test the grid limits follow the local gateway's config.json."""
    mock_powerwall_local_config.return_value = {
        "min_site_meter_power_ac": -3,
        "max_site_meter_power_ac": 9.5,
        "on_grid_solar_curtailment_enabled": False,
    }
    await setup_paired_platform(hass, [Platform.NUMBER])

    freezer.tick(ENERGY_CONFIG_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get("number.energy_site_grid_export_limit").state == "3"
    assert hass.states.get("number.energy_site_grid_import_limit").state == "9.5"
