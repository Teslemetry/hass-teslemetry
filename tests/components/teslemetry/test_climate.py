"""Test the Teslemetry climate platform."""

from copy import deepcopy
from unittest.mock import AsyncMock, _Call, call, patch

import pytest
from pytest_homeassistant.common import mock_restore_cache_with_extra_data
from syrupy.assertion import SnapshotAssertion
from tesla_fleet_api.const import CabinOverheatProtectionTemp
from tesla_fleet_api.exceptions import InvalidCommand
from teslemetry_stream import Signal

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_TEMPERATURE,
    DATA_COMPONENT,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    ClimateEntityFeature,
    ClimateEntityStateAttribute,
    HVACMode,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    STATE_UNKNOWN,
    Platform,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotSupported,
    ServiceValidationError,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import (
    METRIC_SYSTEM,
    US_CUSTOMARY_SYSTEM,
    UnitSystem,
)

from . import assert_entities, reload_platform, setup_platform
from .const import (
    COMMAND_ERRORS,
    COMMAND_IGNORED_REASON,
    COMMAND_OK,
    METADATA,
    METADATA_NOSCOPE,
    VEHICLE_DATA_ALT,
)

VIN = "LRW3F7EK4NC700000"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_climate(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the climate entity is correct."""

    entry = await setup_platform(hass, [Platform.CLIMATE])

    assert_entities(hass, entry.entry_id, entity_registry, snapshot)

    entity_id = "climate.test_climate"

    # Turn On and Set Temp
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: [entity_id],
            ATTR_TEMPERATURE: 20,
            ATTR_HVAC_MODE: HVACMode.HEAT_COOL,
        },
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 20
    assert state.state == HVACMode.HEAT_COOL

    # Set Temp
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: [entity_id],
            ATTR_TEMPERATURE: 21,
        },
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 21

    # Set Preset
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: [entity_id], ATTR_PRESET_MODE: "keep"},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_PRESET_MODE] == "keep"

    # Set Preset
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: [entity_id], ATTR_PRESET_MODE: "off"},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_PRESET_MODE] == "off"

    # Turn Off
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: [entity_id], ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.OFF

    entity_id = "climate.test_cabin_overheat_protection"

    # Turn On and Set Low
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: [entity_id],
            ATTR_TEMPERATURE: 30,
            ATTR_HVAC_MODE: HVACMode.FAN_ONLY,
        },
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 30
    assert state.state == HVACMode.FAN_ONLY

    # Set Temp Medium
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: [entity_id],
            ATTR_TEMPERATURE: 35,
        },
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 35

    # Set Temp High
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: [entity_id],
            ATTR_TEMPERATURE: 40,
        },
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 40

    # Turn Off
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: [entity_id]},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.OFF

    # Turn On
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: [entity_id]},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.COOL

    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 40
    assert state.state == HVACMode.COOL

    # Set Temp between levels snaps to the nearest level
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: [entity_id], ATTR_TEMPERATURE: 34},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 35


@pytest.mark.parametrize(
    ("temperature", "cop_temp"),
    [
        pytest.param(86, CabinOverheatProtectionTemp.LOW, id="low"),
        pytest.param(91, CabinOverheatProtectionTemp.MEDIUM, id="medium"),
        pytest.param(104, CabinOverheatProtectionTemp.HIGH, id="high"),
    ],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default", "mock_legacy")
async def test_cop_set_temperature_fahrenheit(
    hass: HomeAssistant,
    temperature: int,
    cop_temp: CabinOverheatProtectionTemp,
) -> None:
    """Tests a Fahrenheit temperature is snapped to the nearest COP level."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    await setup_platform(hass, [Platform.CLIMATE])
    entity_id = "climate.test_cabin_overheat_protection"

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.set_cop_temp",
        return_value=COMMAND_OK,
    ) as mock_set_cop_temp:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_TEMPERATURE: temperature},
            blocking=True,
        )
    mock_set_cop_temp.assert_called_once_with(cop_temp)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_climate_alt(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_vehicle_data: AsyncMock,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the climate entity is correct."""

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    entry = await setup_platform(hass, [Platform.CLIMATE])
    assert_entities(hass, entry.entry_id, entity_registry, snapshot)


async def test_climate_state_unknown(
    hass: HomeAssistant,
    mock_metadata: AsyncMock,
    mock_vehicle_data: AsyncMock,
) -> None:
    """Test that a missing climate_state_is_climate_on reports unknown, not off."""

    metadata = deepcopy(METADATA)
    metadata["vehicles"]["LRW3F7EK4NC700000"]["polling"] = True
    mock_metadata.return_value = metadata

    data = deepcopy(VEHICLE_DATA_ALT)
    data["response"]["climate_state"]["is_climate_on"] = None
    mock_vehicle_data.return_value = data

    await setup_platform(hass, [Platform.CLIMATE])

    assert hass.states.get("climate.test_climate").state == STATE_UNKNOWN


@pytest.mark.parametrize(
    ("keeper_mode", "preset_mode"),
    [
        pytest.param("on", "keep", id="on"),
        pytest.param("dog", "dog", id="dog"),
        pytest.param("camp", "camp", id="camp"),
        pytest.param("keep", None, id="unmapped"),
        pytest.param(None, None, id="unknown"),
    ],
)
async def test_climate_polling_keeper_mode(
    hass: HomeAssistant,
    mock_metadata: AsyncMock,
    mock_vehicle_data: AsyncMock,
    keeper_mode: str | None,
    preset_mode: str | None,
) -> None:
    """Test that a polling vehicle maps Tesla's climate keeper mode to a preset."""

    metadata = deepcopy(METADATA)
    metadata["vehicles"]["LRW3F7EK4NC700000"]["polling"] = True
    mock_metadata.return_value = metadata

    data = deepcopy(VEHICLE_DATA_ALT)
    data["response"]["climate_state"]["climate_keeper_mode"] = keeper_mode
    mock_vehicle_data.return_value = data

    await setup_platform(hass, [Platform.CLIMATE])

    assert (
        hass.states.get("climate.test_climate").attributes[ATTR_PRESET_MODE]
        == preset_mode
    )


async def test_invalid_error(hass: HomeAssistant, snapshot: SnapshotAssertion) -> None:
    """Tests service error is handled."""

    await setup_platform(hass, platforms=[Platform.CLIMATE])
    entity_id = "climate.test_climate"

    with (
        patch(
            "tesla_fleet_api.teslemetry.Vehicle.auto_conditioning_start",
            side_effect=InvalidCommand,
        ) as mock_on,
        pytest.raises(HomeAssistantError) as error,
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: [entity_id]},
            blocking=True,
        )
    mock_on.assert_called_once()
    assert str(error.value) == snapshot(name="error")


@pytest.mark.parametrize("response", COMMAND_ERRORS)
async def test_errors(hass: HomeAssistant, response: str) -> None:
    """Tests service reason is handled."""

    await setup_platform(hass, platforms=[Platform.CLIMATE])
    entity_id = "climate.test_climate"

    with (
        patch(
            "tesla_fleet_api.teslemetry.Vehicle.auto_conditioning_start",
            return_value=response,
        ) as mock_on,
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: [entity_id]},
            blocking=True,
        )
    mock_on.assert_called_once()


async def test_ignored_error(
    hass: HomeAssistant,
) -> None:
    """Tests ignored error is handled."""

    await setup_platform(hass, [Platform.CLIMATE])
    entity_id = "climate.test_climate"
    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.auto_conditioning_start",
        return_value=COMMAND_IGNORED_REASON,
    ) as mock_on:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: [entity_id]},
            blocking=True,
        )
        mock_on.assert_called_once()


async def test_climate_noscope(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_metadata: AsyncMock,
) -> None:
    """Tests that the climate entity is correct."""
    mock_metadata.return_value = METADATA_NOSCOPE

    entry = await setup_platform(hass, [Platform.CLIMATE])

    entity_entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

    assert entity_entries
    for entity_entry in entity_entries:
        assert entity_entry == snapshot(name=f"{entity_entry.entity_id}-entry")

    entity_id = "climate.test_climate"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_HVAC_MODE: HVACMode.HEAT_COOL},
            blocking=True,
        )

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_TEMPERATURE: 20},
            blocking=True,
        )


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_select_streaming(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
) -> None:
    """Tests that the select entities with streaming are correct."""

    entry = await setup_platform(hass, [Platform.CLIMATE])

    # Stream update
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.INSIDE_TEMP: 26,
                Signal.HVAC_POWER: "HvacPowerStateOn",
                Signal.CLIMATE_KEEPER_MODE: "ClimateKeeperModeOn",
                Signal.RIGHT_HAND_DRIVE: True,
                Signal.HVAC_LEFT_TEMPERATURE_REQUEST: 22,
                Signal.HVAC_RIGHT_TEMPERATURE_REQUEST: 21,
                Signal.CABIN_OVERHEAT_PROTECTION_MODE: (
                    "CabinOverheatProtectionModeStateOn"
                ),
                Signal.CABIN_OVERHEAT_PROTECTION_TEMPERATURE_LIMIT: 35,
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    assert hass.states.get("climate.test_climate") == snapshot(
        name="climate.test_climate LHD"
    )

    await reload_platform(hass, entry, [Platform.CLIMATE])

    # Assert the entities restored their values
    for entity_id in (
        "climate.test_climate",
        "climate.test_cabin_overheat_protection",
    ):
        assert hass.states.get(entity_id) == snapshot(name=entity_id)


@pytest.mark.parametrize(
    (
        "entity_id",
        "units",
        "attributes",
        "extra_data",
        "expected_native",
        "expected_display",
    ),
    [
        pytest.param(
            "climate.test_climate",
            US_CUSTOMARY_SYSTEM,
            {
                ClimateEntityStateAttribute.CURRENT_TEMPERATURE: 70,
                ClimateEntityStateAttribute.TARGET_TEMPERATURE: 72,
                "temperature_unit": (UnitOfTemperature.FAHRENHEIT),
            },
            None,
            (21.111, 22.222),
            (70.0, 72.0),
            id="climate_fahrenheit_on_us_customary",
        ),
        pytest.param(
            "climate.test_climate",
            METRIC_SYSTEM,
            {
                ClimateEntityStateAttribute.CURRENT_TEMPERATURE: 70,
                ClimateEntityStateAttribute.TARGET_TEMPERATURE: 72,
                "temperature_unit": (UnitOfTemperature.FAHRENHEIT),
            },
            None,
            (21.111, 22.222),
            (21.0, 22.0),
            id="climate_fahrenheit_on_metric",
        ),
        pytest.param(
            "climate.test_climate",
            US_CUSTOMARY_SYSTEM,
            {
                ClimateEntityStateAttribute.CURRENT_TEMPERATURE: 21,
                ClimateEntityStateAttribute.TARGET_TEMPERATURE: 22,
                "temperature_unit": (UnitOfTemperature.CELSIUS),
            },
            None,
            (21.0, 22.0),
            (70.0, 71.5),
            id="climate_celsius_on_us_customary",
        ),
        pytest.param(
            "climate.test_climate",
            US_CUSTOMARY_SYSTEM,
            {
                ClimateEntityStateAttribute.CURRENT_TEMPERATURE: 70,
                ClimateEntityStateAttribute.TARGET_TEMPERATURE: 72,
            },
            None,
            (21.111, 22.222),
            (70.0, 72.0),
            id="climate_legacy_on_us_customary",
        ),
        pytest.param(
            "climate.test_climate",
            US_CUSTOMARY_SYSTEM,
            {
                ClimateEntityStateAttribute.CURRENT_TEMPERATURE: 70,
                ClimateEntityStateAttribute.TARGET_TEMPERATURE: 72,
                "temperature_unit": "invalid",
            },
            None,
            (None, None),
            (None, None),
            id="climate_invalid_unit",
        ),
        pytest.param(
            "climate.test_climate",
            US_CUSTOMARY_SYSTEM,
            {
                ClimateEntityStateAttribute.CURRENT_TEMPERATURE: None,
                ClimateEntityStateAttribute.TARGET_TEMPERATURE: None,
                "temperature_unit": (UnitOfTemperature.FAHRENHEIT),
            },
            None,
            (None, None),
            (None, None),
            id="climate_none_values",
        ),
        pytest.param(
            "climate.test_cabin_overheat_protection",
            US_CUSTOMARY_SYSTEM,
            {
                ClimateEntityStateAttribute.CURRENT_TEMPERATURE: 72,
                ClimateEntityStateAttribute.TARGET_TEMPERATURE: 95,
                "temperature_unit": (UnitOfTemperature.FAHRENHEIT),
            },
            None,
            (22.222, 35.0),
            (72, 95),
            id="cop_fahrenheit_on_us_customary",
        ),
        pytest.param(
            "climate.test_cabin_overheat_protection",
            METRIC_SYSTEM,
            {
                ClimateEntityStateAttribute.CURRENT_TEMPERATURE: 72,
                ClimateEntityStateAttribute.TARGET_TEMPERATURE: 95,
                "temperature_unit": (UnitOfTemperature.FAHRENHEIT),
            },
            None,
            (22.222, 35.0),
            (22, 35),
            id="cop_fahrenheit_on_metric",
        ),
        pytest.param(
            "climate.test_cabin_overheat_protection",
            US_CUSTOMARY_SYSTEM,
            {
                ClimateEntityStateAttribute.CURRENT_TEMPERATURE: 72,
                ClimateEntityStateAttribute.TARGET_TEMPERATURE: 95,
            },
            None,
            (22.222, 35.0),
            (72, 95),
            id="cop_legacy_on_us_customary",
        ),
    ],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_streaming_restore_temperature_unit(
    hass: HomeAssistant,
    mock_metadata: AsyncMock,
    entity_id: str,
    units: UnitSystem,
    attributes: dict[str, float | str | None],
    extra_data: dict[str, float | str | None] | None,
    expected_native: tuple[float | None, float | None],
    expected_display: tuple[float | None, float | None],
) -> None:
    """Test restored temperatures are converted to native Celsius."""
    metadata = deepcopy(METADATA)
    metadata["vehicles"][VIN]["config"] = {"cop_user_set_temp_supported": True}
    mock_metadata.return_value = metadata
    hass.config.units = units
    mock_restore_cache_with_extra_data(
        hass, ((State(entity_id, HVACMode.OFF, attributes), extra_data),)
    )

    await setup_platform(hass, [Platform.CLIMATE])

    entity = hass.data[DATA_COMPONENT].get_entity(entity_id)
    assert (
        entity.current_temperature,
        entity.target_temperature,
    ) == pytest.approx(expected_native, abs=1e-3)
    state = hass.states.get(entity_id)
    assert (
        state.attributes[ClimateEntityStateAttribute.CURRENT_TEMPERATURE],
        state.attributes[ClimateEntityStateAttribute.TARGET_TEMPERATURE],
    ) == expected_display


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    ("config", "supported_features"),
    [
        pytest.param(
            {"cop_user_set_temp_supported": True},
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF,
            id="supported",
        ),
        pytest.param(
            {"cop_user_set_temp_supported": False},
            ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF,
            id="unsupported",
        ),
        pytest.param(
            {},
            ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF,
            id="missing",
        ),
    ],
)
async def test_cabin_overheat_protection_streaming_features(
    hass: HomeAssistant,
    mock_metadata: AsyncMock,
    config: dict[str, bool],
    supported_features: ClimateEntityFeature,
) -> None:
    """Test streaming cabin overheat protection features come from metadata config."""

    metadata = deepcopy(METADATA)
    metadata["vehicles"]["LRW3F7EK4NC700000"]["config"] = config
    mock_metadata.return_value = metadata

    await setup_platform(hass, [Platform.CLIMATE])

    state = hass.states.get("climate.test_cabin_overheat_protection")
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == supported_features


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_cabin_overheat_protection_streaming_set_temperature(
    hass: HomeAssistant,
    mock_metadata: AsyncMock,
) -> None:
    """Test setting the streaming cabin overheat protection temperature."""

    metadata = deepcopy(METADATA)
    metadata["vehicles"]["LRW3F7EK4NC700000"]["config"] = {
        "cop_user_set_temp_supported": True
    }
    mock_metadata.return_value = metadata

    await setup_platform(hass, [Platform.CLIMATE])
    entity_id = "climate.test_cabin_overheat_protection"

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.set_cop_temp",
        return_value=COMMAND_OK,
    ) as mock_set_cop_temp:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_TEMPERATURE: 35},
            blocking=True,
        )
    mock_set_cop_temp.assert_called_once_with(CabinOverheatProtectionTemp.MEDIUM)
    assert hass.states.get(entity_id).attributes[ATTR_TEMPERATURE] == 35


@pytest.mark.parametrize(
    ("rhd", "target_temperature"),
    [
        pytest.param(True, 21, id="rhd"),
        pytest.param(False, 22, id="lhd"),
    ],
)
async def test_climate_streaming_drive_side(
    hass: HomeAssistant,
    mock_metadata: AsyncMock,
    mock_add_listener: AsyncMock,
    rhd: bool,
    target_temperature: float,
) -> None:
    """Test the streaming target temperature follows the driver side from metadata."""

    metadata = deepcopy(METADATA)
    metadata["vehicles"][VIN]["config"] = {"rhd": rhd}
    mock_metadata.return_value = metadata

    await setup_platform(hass, [Platform.CLIMATE])

    mock_add_listener.send(
        {
            "vin": VIN,
            "data": {
                Signal.HVAC_LEFT_TEMPERATURE_REQUEST: 22,
                Signal.HVAC_RIGHT_TEMPERATURE_REQUEST: 21,
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    state = hass.states.get("climate.test_climate")
    assert state.attributes[ATTR_TEMPERATURE] == target_temperature


@pytest.mark.parametrize(
    ("hvac_power", "expected"),
    [
        pytest.param("HvacPowerStateOn", HVACMode.HEAT_COOL, id="on"),
        pytest.param(
            "HvacPowerStatePrecondition", HVACMode.HEAT_COOL, id="precondition"
        ),
        pytest.param("HvacPowerStateOverheatProtect", HVACMode.OFF, id="overheat"),
        pytest.param("HvacPowerStateOff", HVACMode.OFF, id="off"),
    ],
)
async def test_climate_streaming_hvac_power(
    hass: HomeAssistant,
    mock_add_listener: AsyncMock,
    hvac_power: str,
    expected: HVACMode,
) -> None:
    """Tests the HvacPower to HVAC mode mapping for streaming vehicles."""

    await setup_platform(hass, [Platform.CLIMATE])

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {Signal.HVAC_POWER: hvac_power},
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    assert hass.states.get("climate.test_climate").state == expected


PASSENGER_ENTITY_ID = "climate.test_passenger_climate"
PASSENGER_SYNC_FEATURES = (
    ClimateEntityFeature.TURN_ON
    | ClimateEntityFeature.TURN_OFF
    | ClimateEntityFeature.PRESET_MODE
)
PASSENGER_SPLIT_FEATURES = (
    PASSENGER_SYNC_FEATURES | ClimateEntityFeature.TARGET_TEMPERATURE
)


def send_set_points(
    mock_add_listener: AsyncMock, left: float | None, right: float | None
) -> None:
    """Send the front set points as streamed by the vehicle."""
    mock_add_listener.send(
        {
            "vin": VIN,
            "data": {
                Signal.HVAC_LEFT_TEMPERATURE_REQUEST: left,
                Signal.HVAC_RIGHT_TEMPERATURE_REQUEST: right,
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )


@pytest.mark.parametrize(
    ("rhd", "left", "right", "preset_mode", "supported_features", "temperature"),
    [
        pytest.param(
            False, 22, 22, "sync", PASSENGER_SYNC_FEATURES, None, id="lhd_sync"
        ),
        pytest.param(
            False, 22, 24, "split", PASSENGER_SPLIT_FEATURES, 24, id="lhd_split"
        ),
        pytest.param(
            True, 24, 22, "split", PASSENGER_SPLIT_FEATURES, 24, id="rhd_split"
        ),
        pytest.param(
            False, None, 24, None, PASSENGER_SYNC_FEATURES, None, id="driver_unknown"
        ),
    ],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_passenger_climate_streaming_preset(
    hass: HomeAssistant,
    mock_metadata: AsyncMock,
    mock_add_listener: AsyncMock,
    rhd: bool,
    left: float | None,
    right: float | None,
    preset_mode: str | None,
    supported_features: ClimateEntityFeature,
    temperature: float | None,
) -> None:
    """Test the passenger preset follows the set points and gates the temperature."""
    metadata = deepcopy(METADATA)
    metadata["vehicles"][VIN]["config"] = {"rhd": rhd}
    mock_metadata.return_value = metadata

    await setup_platform(hass, [Platform.CLIMATE])
    send_set_points(mock_add_listener, left, right)
    await hass.async_block_till_done()

    state = hass.states.get(PASSENGER_ENTITY_ID)
    assert state.attributes[ATTR_PRESET_MODE] == preset_mode
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == supported_features
    assert state.attributes.get(ATTR_TEMPERATURE) == temperature


@pytest.mark.parametrize(
    ("driver_setting", "passenger_setting", "preset_mode", "supported_features"),
    [
        pytest.param(22, 22, "sync", PASSENGER_SYNC_FEATURES, id="sync"),
        pytest.param(22, 24, "split", PASSENGER_SPLIT_FEATURES, id="split"),
        pytest.param(None, 24, None, PASSENGER_SYNC_FEATURES, id="driver_unknown"),
    ],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_passenger_climate_polling_preset(
    hass: HomeAssistant,
    mock_metadata: AsyncMock,
    mock_vehicle_data: AsyncMock,
    driver_setting: float | None,
    passenger_setting: float,
    preset_mode: str | None,
    supported_features: ClimateEntityFeature,
) -> None:
    """Test the polling passenger preset follows the vehicle_data set points."""
    metadata = deepcopy(METADATA)
    metadata["vehicles"][VIN]["polling"] = True
    mock_metadata.return_value = metadata

    data = deepcopy(VEHICLE_DATA_ALT)
    data["response"]["climate_state"]["driver_temp_setting"] = driver_setting
    data["response"]["climate_state"]["passenger_temp_setting"] = passenger_setting
    mock_vehicle_data.return_value = data

    await setup_platform(hass, [Platform.CLIMATE])

    state = hass.states.get(PASSENGER_ENTITY_ID)
    assert state.attributes[ATTR_PRESET_MODE] == preset_mode
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == supported_features


@pytest.mark.parametrize(
    ("service_data", "expected_calls", "hvac_state"),
    [
        pytest.param({}, [], STATE_UNKNOWN, id="temperature"),
        pytest.param(
            {ATTR_HVAC_MODE: HVACMode.HEAT_COOL},
            [call()],
            HVACMode.HEAT_COOL,
            id="temperature_and_hvac_mode",
        ),
    ],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_passenger_climate_set_temperature(
    hass: HomeAssistant,
    mock_add_listener: AsyncMock,
    service_data: dict[str, HVACMode],
    expected_calls: list[_Call],
    hvac_state: str,
) -> None:
    """Test a split passenger temperature is sent with the driver temperature kept."""
    await setup_platform(hass, [Platform.CLIMATE])
    send_set_points(mock_add_listener, 22, 24)
    await hass.async_block_till_done()

    with (
        patch(
            "tesla_fleet_api.teslemetry.Vehicle.set_temps", return_value=COMMAND_OK
        ) as mock_set_temps,
        patch(
            "tesla_fleet_api.teslemetry.Vehicle.auto_conditioning_start",
            return_value=COMMAND_OK,
        ) as mock_start,
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {
                ATTR_ENTITY_ID: [PASSENGER_ENTITY_ID],
                ATTR_TEMPERATURE: 20,
                **service_data,
            },
            blocking=True,
        )
    mock_set_temps.assert_called_once_with(driver_temp=22, passenger_temp=20)
    assert mock_start.call_args_list == expected_calls

    state = hass.states.get(PASSENGER_ENTITY_ID)
    assert state.state == hvac_state
    assert state.attributes[ATTR_TEMPERATURE] == 20
    assert state.attributes[ATTR_PRESET_MODE] == "split"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_passenger_climate_set_temperature_sync(
    hass: HomeAssistant,
    mock_add_listener: AsyncMock,
) -> None:
    """Test a synced passenger temperature cannot be set."""
    await setup_platform(hass, [Platform.CLIMATE])
    send_set_points(mock_add_listener, 22, 22)
    await hass.async_block_till_done()

    with (
        patch("tesla_fleet_api.teslemetry.Vehicle.set_temps") as mock_set_temps,
        pytest.raises(ServiceNotSupported),
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: [PASSENGER_ENTITY_ID], ATTR_TEMPERATURE: 20},
            blocking=True,
        )
    mock_set_temps.assert_not_called()


@pytest.mark.parametrize(
    (
        "passenger_set_point",
        "preset_mode",
        "expected_calls",
        "supported_features",
        "temperature",
    ),
    [
        pytest.param(
            24,
            "sync",
            [call(driver_temp=22, passenger_temp=22)],
            PASSENGER_SYNC_FEATURES,
            None,
            id="sync",
        ),
        pytest.param(22, "split", [], PASSENGER_SPLIT_FEATURES, 22, id="split"),
    ],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_passenger_climate_set_preset_mode(
    hass: HomeAssistant,
    mock_add_listener: AsyncMock,
    passenger_set_point: float,
    preset_mode: str,
    expected_calls: list[_Call],
    supported_features: ClimateEntityFeature,
    temperature: float | None,
) -> None:
    """Test sync sends the driver temperature to both seats and split unlocks the temperature."""
    await setup_platform(hass, [Platform.CLIMATE])
    send_set_points(mock_add_listener, 22, passenger_set_point)
    await hass.async_block_till_done()

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.set_temps", return_value=COMMAND_OK
    ) as mock_set_temps:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_ENTITY_ID: [PASSENGER_ENTITY_ID], ATTR_PRESET_MODE: preset_mode},
            blocking=True,
        )
    assert mock_set_temps.call_args_list == expected_calls

    state = hass.states.get(PASSENGER_ENTITY_ID)
    assert state.attributes[ATTR_PRESET_MODE] == preset_mode
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == supported_features
    assert state.attributes.get(ATTR_TEMPERATURE) == temperature


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_passenger_climate_set_preset_mode_driver_unknown(
    hass: HomeAssistant,
) -> None:
    """Test the preset cannot change before the driver set point is known."""
    await setup_platform(hass, [Platform.CLIMATE])

    with (
        patch("tesla_fleet_api.teslemetry.Vehicle.set_temps") as mock_set_temps,
        pytest.raises(HomeAssistantError) as error,
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_ENTITY_ID: [PASSENGER_ENTITY_ID], ATTR_PRESET_MODE: "sync"},
            blocking=True,
        )
    assert error.value.translation_key == "driver_temperature_unknown"
    mock_set_temps.assert_not_called()


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_passenger_climate_turn_on_off(hass: HomeAssistant) -> None:
    """Test the passenger climate turns the cabin climate on and off."""
    await setup_platform(hass, [Platform.CLIMATE])

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.auto_conditioning_stop",
        return_value=COMMAND_OK,
    ) as mock_stop:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: [PASSENGER_ENTITY_ID]},
            blocking=True,
        )
    mock_stop.assert_called_once()
    assert hass.states.get(PASSENGER_ENTITY_ID).state == HVACMode.OFF

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.auto_conditioning_start",
        return_value=COMMAND_OK,
    ) as mock_start:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: [PASSENGER_ENTITY_ID]},
            blocking=True,
        )
    mock_start.assert_called_once()
    assert hass.states.get(PASSENGER_ENTITY_ID).state == HVACMode.HEAT_COOL


@pytest.mark.parametrize(
    ("passenger_set_point", "passenger_temp"),
    [
        pytest.param(24, 24, id="split"),
        pytest.param(22, 20, id="sync"),
        pytest.param(None, 20, id="passenger_unknown"),
    ],
)
async def test_climate_streaming_set_temperature_passenger(
    hass: HomeAssistant,
    mock_add_listener: AsyncMock,
    passenger_set_point: float | None,
    passenger_temp: float,
) -> None:
    """Test the driver temperature keeps a split passenger temperature."""
    await setup_platform(hass, [Platform.CLIMATE])
    send_set_points(mock_add_listener, 22, passenger_set_point)
    await hass.async_block_till_done()

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.set_temps", return_value=COMMAND_OK
    ) as mock_set_temps:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: ["climate.test_climate"], ATTR_TEMPERATURE: 20},
            blocking=True,
        )
    mock_set_temps.assert_called_once_with(
        driver_temp=20, passenger_temp=passenger_temp
    )


@pytest.mark.parametrize(
    ("passenger_setting", "passenger_temp"),
    [
        pytest.param(24, 24, id="split"),
        pytest.param(22, 20, id="sync"),
    ],
)
async def test_climate_polling_set_temperature_passenger(
    hass: HomeAssistant,
    mock_metadata: AsyncMock,
    mock_vehicle_data: AsyncMock,
    passenger_setting: float,
    passenger_temp: float,
) -> None:
    """Test the polling driver temperature keeps a split passenger temperature."""
    metadata = deepcopy(METADATA)
    metadata["vehicles"][VIN]["polling"] = True
    mock_metadata.return_value = metadata

    data = deepcopy(VEHICLE_DATA_ALT)
    data["response"]["climate_state"]["driver_temp_setting"] = 22
    data["response"]["climate_state"]["passenger_temp_setting"] = passenger_setting
    mock_vehicle_data.return_value = data

    await setup_platform(hass, [Platform.CLIMATE])

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.set_temps", return_value=COMMAND_OK
    ) as mock_set_temps:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: ["climate.test_climate"], ATTR_TEMPERATURE: 20},
            blocking=True,
        )
    mock_set_temps.assert_called_once_with(
        driver_temp=20, passenger_temp=passenger_temp
    )
