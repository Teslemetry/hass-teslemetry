"""Constants used by Teslemetry integration."""

from enum import StrEnum
import logging

DOMAIN = "teslemetry"

LOGGER = logging.getLogger(__package__)

# OAuth
AUTHORIZE_URL = "https://teslemetry.com/connect"
TOKEN_URL = "https://api.teslemetry.com/oauth/token"
CLIENT_ID = "homeassistant"

# Config subentry types
SUBENTRY_TYPE_VEHICLE = "vehicle"
SUBENTRY_TYPE_ENERGY_SITE = "energy_site"

# Subentry data keys. An energy site subentry also stores CONF_HOST and
# CONF_PASSWORD (from homeassistant.const) once paired for local TEDAPI v1r
# access; their presence enables Powerwall-first command routing.
CONF_SITE_ID = "site_id"

# File holding the integration's RSA private key used to sign TEDAPI v1r
# requests. The matching public key is what gets registered as an authorized
# client on the energy gateway when pairing.
RSA_KEY_FILE = "teslemetry_rsa.key"

# hass.data key for the shared Teslemetry instance holding the RSA key.
RSA_PARENT_KEY = f"{DOMAIN}_rsa_parent"

# Number of list_authorized_clients() polls, and the delay between them, while
# waiting for the user to approve the pending key in the Tesla app.
KEY_PAIRING_POLL_ATTEMPTS = 10
KEY_PAIRING_POLL_INTERVAL = 2

ENERGY_HISTORY_FIELDS = [
    "solar_energy_exported",
    "generator_energy_exported",
    "grid_energy_imported",
    "grid_services_energy_imported",
    "grid_services_energy_exported",
    "grid_energy_exported_from_solar",
    "grid_energy_exported_from_generator",
    "grid_energy_exported_from_battery",
    "battery_energy_exported",
    "battery_energy_imported_from_grid",
    "battery_energy_imported_from_solar",
    "battery_energy_imported_from_generator",
    "consumer_energy_imported_from_grid",
    "consumer_energy_imported_from_solar",
    "consumer_energy_imported_from_battery",
    "consumer_energy_imported_from_generator",
    "total_home_usage",
    "total_battery_charge",
    "total_battery_discharge",
    "total_solar_generation",
    "total_grid_energy_exported",
]


# Vehicle metadata "issue" values that map to an actionable repair issue, with
# an optional "learn more" URL the user can visit to resolve it. The "no_data"
# issue is intentionally ignored as it is not user-actionable.
VEHICLE_ISSUE_LEARN_MORE: dict[str, str | None] = {
    "key": "https://teslemetry.com/key",
    "streaming_toggle": None,
}


class TeslemetryState(StrEnum):
    """Teslemetry Vehicle States."""

    ONLINE = "online"
    ASLEEP = "asleep"
    OFFLINE = "offline"


class TeslemetryClimateSide(StrEnum):
    """Teslemetry Climate Keeper Modes."""

    DRIVER = "driver_temp"
    PASSENGER = "passenger_temp"
