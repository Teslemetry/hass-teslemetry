"""Write documentation."""

from itertools import chain
import json
from custom_components.teslemetry.binary_sensor import (
    VEHICLE_DESCRIPTIONS as BINARY_VEHICLE_DESCRIPTIONS,
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
    VEHICLE_TIME_DESCRIPTIONS as SENSOR_VEHICLE_TIME_DESCRIPTIONS,
    ENERGY_INFO_DESCRIPTIONS as SENSOR_ENERGY_INFO_DESCRIPTIONS,
    ENERGY_LIVE_DESCRIPTIONS as SENSOR_ENERGY_LIVE_DESCRIPTIONS,
    WALL_CONNECTOR_DESCRIPTIONS as SENSOR_WALL_CONNECTOR_DESCRIPTIONS,
)
from custom_components.teslemetry.switch import (
    VEHICLE_DESCRIPTIONS as SWITCH_VEHICLE_DESCRIPTIONS,
)

# Load strings.json
#strings = json.load(open("custom_components/teslemetry/strings.json"))
en = json.load(open("custom_components/teslemetry/translations/en.json"))
icons = json.load(open("custom_components/teslemetry/icons.json"))

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
domain_names = {
    'binary_sensor': "Binary sensor",
    'device_tracker': "Device tracker",
    'button': "Button",
    'cover': "Cover",
    'climate': "Climate",
    'number': "Number",
    'media_player': "Media player",
    'lock': "Lock",
    'select': "Select",
    'sensor': "Sensor",
    'switch': "Switch",
    'update': "Update"
}
# Iterate over all entities
output = []
for domain, type, descriptions in (
    (
        "binary_sensor",
        "Vehicle",
        BINARY_VEHICLE_DESCRIPTIONS,
    ),
    (
        "binary_sensor",
        "Energy Site",
        chain(
            BINARY_ENERGY_LIVE_DESCRIPTIONS,
            BINARY_ENERGY_INFO_DESCRIPTIONS,
        ),
    ),
    ("button", "Vehicle", BUTTON_DESCRIPTIONS),
    ("number", "Vehicle", NUMBER_VEHICLE_DESCRIPTIONS),
    ("number", "Energy Site", NUMBER_ENERGY_INFO_DESCRIPTIONS),
    ("select", "Vehicle", SELECT_SEAT_HEATER_DESCRIPTIONS),
    (
        "sensor",
        "Vehicle",
        chain(
            SENSOR_VEHICLE_DESCRIPTIONS,
            SENSOR_VEHICLE_TIME_DESCRIPTIONS,
        )
    ),(
        "sensor",
        "Energy Site",
        chain(
            SENSOR_ENERGY_INFO_DESCRIPTIONS,
            SENSOR_ENERGY_LIVE_DESCRIPTIONS
        ),
    ),(
        "sensor",
        "Wall Connector",
        SENSOR_WALL_CONNECTOR_DESCRIPTIONS,
    ),
    ("switch", "Vehicle", SWITCH_VEHICLE_DESCRIPTIONS),
):
    for description in descriptions:
        key = description.key
        translation_key = description.key
        #if key not in strings["entity"][domain]:
        #    print(f"No string for {domain} {key}")
        if translation_key not in en["entity"][domain]:
            print(f"ISSUE: No en for {domain} {translation_key}")
        else:
            used.append((domain, translation_key))

        if not description.device_class and translation_key not in icons["entity"][domain]:
            print(f"ISSUE: No icon for {domain} {translation_key}")

        method = ""
        streaming = hasattr(description, "streaming_key") and description.streaming_key is not None
        polling = hasattr(description, "polling_parent") and description.polling_parent is not None
        if streaming and polling:
            method = "Both"
        elif streaming:
            method = "Streaming"
        elif polling:
            method = "Polling"

        enabled = "Yes"
        if description.entity_registry_enabled_default == False:
            enabled = "No"

        #output.append(
        #    f"|{type}|{domain_names[domain]}|{en['entity'][domain][translation_key]['name']}|{method}|{enabled}|"
        #)

extras = [
    ("Vehicle","button","refresh","Polling","Yes"),
    ("Energy site","select","default_real_mode","Polling","Yes"),
    ("Energy site","select","components_customer_preferred_export_rule","Polling","Yes"),
    ("Vehicle","sensor","charge_state_minutes_to_full_charge_timestamp","Polling","Yes"),
    ("Vehicle","sensor","drive_state_active_route_minutes_to_arrival_timestamp","Polling","Yes"),
    ("Vehicle","switch","charge_state_user_charge_enable_request","Polling","Yes"),
    ("Vehicle","select","climate_state_steering_wheel_heat_level","Polling","Yes"),
    ("Energy site","switch","user_settings_storm_mode_enabled","Polling","Yes"),
    ("Energy site","switch","components_disallow_charge_from_grid_with_solar_installed","Polling","Yes"),
    ("Wall connector","sensor","vin","Polling","Yes"),
    ("Vehicle","climate","driver_temp","Polling^1","Yes"),
    ("Vehicle","climate","climate_state_cabin_overheat_protection","Both^1","Yes"),
    ("Vehicle","cover","windows","Polling","Yes"),
    ("Vehicle","cover","charge_state_charge_port_door_open","Both","Yes"),
    ("Vehicle","cover","vehicle_state_ft","Polling","Yes"),
    ("Vehicle","cover","vehicle_state_rt","Polling","Yes"),
    ("Vehicle","device_tracker","location","Both","Yes"),
    ("Vehicle","device_tracker","route","Polling","Yes"),
    ("Vehicle","lock","vehicle_state_locked","Both","Yes"),
    ("Vehicle","lock","charge_state_charge_port_latch","Both","Yes"),
    ("Vehicle","lock","vehicle_state_speed_limit_mode_active","Both","Yes"),
    ("Vehicle","media_player","media","Polling","Yes"),
    ("Vehicle","update","vehicle_state_software_update_status","Both^2","Yes"),


]

for type, domain, key, method, enabled in extras:
    output.append(
        f"|{type}|{domain_names[domain]}|{en['entity'][domain][key]['name']}|{method}|{enabled}|"
    )
output.sort()
# write output to file
with open("documentation.md", "w") as f:
    f.write("|Device|Domain|Name|Method|Enabled|\n")
    f.write("|---|---|---|---|---|\n")
    f.write("\n".join(output))
    f.write("\n\n^1 Only inside temperature is streamable\n^2 Only version is streamable\n")

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
                "user_settings_storm_mode_enabled",
                "components_disallow_charge_from_grid_with_solar_installed",
                "vin",
            ):
                if (domain, key) not in used:
                    print(f"UNUSED: {domain} {key}")
