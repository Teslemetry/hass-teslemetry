"""Write documentation"""

from enum import Enum
from tesla_fleet_api.const import TelemetryField
from itertools import chain
import json
from custom_components.teslemetry.binary_sensor import (
    VEHICLE_DESCRIPTIONS as BINARY_VEHICLE_DESCRIPTIONS,
    VEHICLE_STREAM_DESCRIPTIONS as BINARY_VEHICLE_STREAM_DESCRIPTIONS,
    ENERGY_LIVE_DESCRIPTIONS as BINARY_ENERGY_LIVE_DESCRIPTIONS,
    ENERGY_INFO_DESCRIPTIONS as BINARY_ENERGY_INFO_DESCRIPTIONS,
)
from custom_components.teslemetry.button import DESCRIPTIONS as BUTTON_DESCRIPTIONS
from custom_components.teslemetry.number import (
    VEHICLE_DESCRIPTIONS as NUMBER_VEHICLE_DESCRIPTIONS,
    ENERGY_INFO_DESCRIPTIONS as NUMBER_ENERGY_INFO_DESCRIPTIONS,
)
from custom_components.teslemetry.select import (
    SEAT_HEATER_DESCRIPTIONS as SELECT_SEAT_HEATER_DESCRIPTIONS,
)
from custom_components.teslemetry.sensor import (
    VEHICLE_DESCRIPTIONS as SENSOR_VEHICLE_DESCRIPTIONS,
    VEHICLE_STREAM_DESCRIPTIONS as SENSOR_VEHICLE_STREAM_DESCRIPTIONS,
    VEHICLE_TIME_DESCRIPTIONS as SENSOR_VEHICLE_TIME_DESCRIPTIONS,
    ENERGY_INFO_DESCRIPTIONS as SENSOR_ENERGY_INFO_DESCRIPTIONS,
    ENERGY_LIVE_DESCRIPTIONS as SENSOR_ENERGY_LIVE_DESCRIPTIONS,
    WALL_CONNECTOR_DESCRIPTIONS as SENSOR_WALL_CONNECTOR_DESCRIPTIONS,
)
from custom_components.teslemetry.switch import (
    VEHICLE_DESCRIPTIONS as SWITCH_VEHICLE_DESCRIPTIONS,
)

# Load strings.json
strings = json.load(open("custom_components/teslemetry/strings.json"))
en = json.load(open("custom_components/teslemetry/translations/en.json"))


# Recursively compare keys from strings.json and en.json
def compare_keys(a, b, parent=""):
    for key, value in a.items():
        if key not in b:
            print(f"{parent}{key} not found")
        elif isinstance(value, dict):
            compare_keys(value, b[key], f"{parent}{key}.")


# compare_keys(strings, en, "strings.json ")
# compare_keys(en, strings, "en.json ")

used = []
streaming_used = []
domains = ("binary_sensor", "button", "number", "select", "sensor", "switch")

# Check for missing
for domain, descriptions in (
    (
        "binary_sensor",
        chain(
            BINARY_VEHICLE_DESCRIPTIONS,
            BINARY_ENERGY_LIVE_DESCRIPTIONS,
            BINARY_ENERGY_INFO_DESCRIPTIONS,
            BINARY_VEHICLE_STREAM_DESCRIPTIONS,
        ),
    ),
    ("button", BUTTON_DESCRIPTIONS),
    ("number", chain(NUMBER_VEHICLE_DESCRIPTIONS, NUMBER_ENERGY_INFO_DESCRIPTIONS)),
    ("select", SELECT_SEAT_HEATER_DESCRIPTIONS),
    (
        "sensor",
        chain(
            SENSOR_VEHICLE_DESCRIPTIONS,
            SENSOR_VEHICLE_TIME_DESCRIPTIONS,
            SENSOR_ENERGY_INFO_DESCRIPTIONS,
            SENSOR_ENERGY_LIVE_DESCRIPTIONS,
            SENSOR_WALL_CONNECTOR_DESCRIPTIONS,
            SENSOR_VEHICLE_STREAM_DESCRIPTIONS,
        ),
    ),
    ("switch", SWITCH_VEHICLE_DESCRIPTIONS),
):
    for description in descriptions:
        if isinstance(description.key, TelemetryField):
            key = f"{description.key.value}"
            translation_key = f"stream_{description.key.value.lower()}"
        else:
            key = description.key
            translation_key = description.key
        # if key not in strings["entity"][domain]:
        #    print(f"No string for {domain} {key}")
        if translation_key not in en["entity"][domain]:
            print(f"ISSUE: No en for {domain} {translation_key}")
        else:
            used.append((domain, translation_key))

        if (
            hasattr(description, "streaming_key")
            and description.streaming_key is not None
        ):
            streaming_used.append(description.streaming_key.value)
            print(
                f"['{description.streaming_key.value}','{domain}.*_{en['entity'][domain][translation_key]['name'].lower().replace(' ','_')}','Polling & Streaming'],"
            )
        if isinstance(description.key, TelemetryField):
            if description.key.value in streaming_used:
                print(f"DUPLICATE: {description.key.value}")
            else:
                streaming_used.append(description.key.value)
            print(
                f"['{description.key.value}','{domain}.*_{en['entity'][domain][translation_key]['name'].lower().replace(' ','_')}','Streaming'],"
            )

# Check for unused
for domain in en["entity"]:
    if domain in domains:
        for key in en["entity"][domain]:
            if key not in (
                "refresh",
                "default_real_mode",
                "components_customer_preferred_export_rule",
                "charge_state_minutes_to_full_charge_timestamp",
                "drive_state_active_route_minutes_to_arrival_timestamp",
                "charge_state_user_charge_enable_request",
                "climate_state_steering_wheel_heat_level",
                "storm_mode_enabled",
                "components_disallow_charge_from_grid_with_solar_installed",
            ):
                if (domain, key) not in used:
                    print(f"UNUSED: {domain} {key}")
