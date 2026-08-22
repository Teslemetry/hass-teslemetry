"""Teslemetry integration."""

import asyncio
from collections.abc import Callable
from copy import deepcopy
from functools import partial
from pathlib import Path
from typing import Any, Final, cast

from aiohttp import ClientError
from aiopowerwall import PowerwallClient, PowerwallEnergySite, PowerwallError
from bleak.exc import BleakError
from tesla_fleet_api.const import Scope
from tesla_fleet_api.exceptions import (
    Forbidden,
    InvalidToken,
    LoginRequired,
    SubscriptionRequired,
    TeslaFleetError,
    TeslemetryRegistrationError,
)
from tesla_fleet_api.router import VehicleRouter
from tesla_fleet_api.tesla import EnergySiteRouter
from tesla_fleet_api.teslemetry import EnergySite, Teslemetry, Vehicle
from teslemetry_stream import TeslemetryStream
from teslemetry_stream.const import SseTopic

from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_ADDRESS,
    CONF_HOST,
    CONF_PASSWORD,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    OAuth2TokenRequestError,
    OAuth2TokenRequestReauthError,
)
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    ImplementationUnavailableError,
    OAuth2Session,
    async_get_config_entry_implementation,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import UpdateFailed

from .ble import TeslemetryBLEDataManager
from .const import (
    CLIENT_ID,
    CONF_VIN,
    DOMAIN,
    LOGGER,
    POWERWALL_KEY_FILE,
    RSA_PARENT_KEY,
    SUBENTRY_TYPE_ENERGY_SITE,
    SUBENTRY_TYPE_VEHICLE,
    VEHICLE_ISSUE_LEARN_MORE,
)
from .coordinator import (
    TeslemetryEnergyHistoryCoordinator,
    TeslemetryEnergySiteInfoCoordinator,
    TeslemetryEnergySiteLiveCoordinator,
    TeslemetryEnergySiteLiveLocalCoordinator,
    TeslemetryMetadataCoordinator,
    TeslemetryVehicleDataCoordinator,
)
from .helpers import (
    async_get_ble_parent,
    async_handle_credits,
    async_update_device_sw_version,
    flatten,
    insufficient_credits_issue_id,
    local_control_issue_id,
)
from .logship import CONF_SHIP_LOGS_TO_CLICKSTACK, async_get_or_create_logship
from .models import TeslemetryData, TeslemetryEnergyData, TeslemetryVehicleData
from .oauth import async_ensure_client_credential
from .services import async_setup_services

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.DEVICE_TRACKER,
    Platform.LOCK,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

type TeslemetryConfigEntry = ConfigEntry[TeslemetryData]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Exact SSE topics the integration consumes. An explicit allowlist keeps a
# new server topic from silently adding traffic or data exposure to HA.
STREAM_TOPICS: Final = (
    SseTopic.STATE,
    SseTopic.VEHICLE_DATA,
    SseTopic.DATA,
    SseTopic.CONNECTIVITY,
    SseTopic.CREDITS,
    SseTopic.LIVE_STATUS,
    SseTopic.SITE_INFO,
    SseTopic.TARIFF_CONTENT_V2,
)

# Ceiling on the on-unload Bluetooth disconnect. A wedged adapter that never
# returns must not strand the entry in unload; giving up beats never reloading.
BLE_DISCONNECT_TIMEOUT: Final = 5


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Telemetry integration."""
    # A v1 entry migrates using the legacy static client_id (async_migrate_entry);
    # registering a DCR client first would leave auth_implementation pointing at
    # a client_id that never minted that entry's refresh token.
    if not any(
        entry.version == 1 for entry in hass.config_entries.async_entries(DOMAIN)
    ):
        try:
            await async_ensure_client_credential(hass)
        except TeslemetryRegistrationError as err:
            # Registration is retried when the user starts the config flow, so a
            # transient failure here must not block integration setup.
            LOGGER.debug("Deferring Teslemetry client registration: %s", err)
    async_setup_services(hass)
    return True


async def _get_access_token(oauth_session: OAuth2Session) -> str:
    """Get a valid access token, refreshing if necessary."""
    LOGGER.debug(
        "Token valid: %s, expires_at: %s",
        oauth_session.valid_token,
        oauth_session.token.get("expires_at"),
    )
    setup_in_progress = (
        oauth_session.config_entry.state is ConfigEntryState.SETUP_IN_PROGRESS
    )
    try:
        await oauth_session.async_ensure_token_valid()
    except OAuth2TokenRequestReauthError as err:
        if setup_in_progress:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
            ) from err
        # Not in setup: let the coordinator's own OAuth2TokenRequestError
        # handling stop polling and (re)start reauth without tearing
        # down the already-loaded entry.
        oauth_session.config_entry.async_start_reauth(oauth_session.hass)
        raise
    except OAuth2TokenRequestError as err:
        # Recoverable (e.g. 429/5xx). During setup this backs off via the
        # normal ConfigEntryNotReady retry; once loaded, let it propagate so
        # the coordinator treats it as a transient failed update instead.
        if setup_in_progress:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="not_ready_connection_error",
            ) from err
        raise
    except (KeyError, TypeError) as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="token_data_malformed",
        ) from err
    except ClientError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="not_ready_connection_error",
        ) from err
    return cast(str, oauth_session.token[CONF_ACCESS_TOKEN])


def _get_subscribed_ids_from_metadata(
    data: dict[str, Any],
) -> tuple[set[str], set[str]]:
    """Return metadata device IDs that have an active subscription."""
    subscribed_vins = {
        vin for vin, info in data["vehicles"].items() if info.get("access")
    }
    subscribed_site_ids = {
        site_id for site_id, info in data["energy_sites"].items() if info.get("access")
    }

    return subscribed_vins, subscribed_site_ids


def _setup_dynamic_discovery(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    metadata_coordinator: TeslemetryMetadataCoordinator,
    known_vins: set[str],
    known_site_ids: set[str],
) -> None:
    """Set up dynamic device discovery via reload when subscriptions change."""

    @callback
    def _handle_metadata_update() -> None:
        """Handle metadata coordinator update - detect subscription changes."""
        data = metadata_coordinator.data
        if not data:
            return

        current_vins, current_site_ids = _get_subscribed_ids_from_metadata(data)

        added_vins = current_vins - known_vins
        removed_vins = known_vins - current_vins
        added_sites = current_site_ids - known_site_ids
        removed_sites = known_site_ids - current_site_ids

        if added_vins or removed_vins or added_sites or removed_sites:
            LOGGER.info(
                "Tesla subscription changes detected "
                "(added vehicles: %s, removed vehicles: %s, "
                "added energy sites: %s, removed energy sites: %s), "
                "reloading integration",
                added_vins or "none",
                removed_vins or "none",
                added_sites or "none",
                removed_sites or "none",
            )
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(
        metadata_coordinator.async_add_listener(_handle_metadata_update)
    )


def _async_update_vehicle_repairs(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    vins: set[str],
    vehicle_metadata: dict[str, Any],
) -> None:
    """Create or remove repair issues based on each vehicle's metadata issue."""
    for vin in vins | set(vehicle_metadata):
        info = vehicle_metadata.get(vin, {})
        issue = info.get("issue")
        for issue_type, learn_more_url in VEHICLE_ISSUE_LEARN_MORE.items():
            issue_id = f"{issue_type}_{vin}"
            if vin in vins and info.get("access") and issue == issue_type:
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=True,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=issue_type,
                    translation_placeholders={"vehicle": info.get("name") or vin},
                    learn_more_url=learn_more_url,
                    data={
                        "entry_id": entry.entry_id,
                        "vin": vin,
                        "issue_type": issue_type,
                        "vehicle": info.get("name") or vin,
                    },
                )
            else:
                ir.async_delete_issue(hass, DOMAIN, issue_id)


def _setup_vehicle_repairs(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    metadata_coordinator: TeslemetryMetadataCoordinator,
    vins: set[str],
    vehicle_metadata: dict[str, Any],
) -> None:
    """Track vehicle metadata issues and keep repair issues in sync."""

    _async_update_vehicle_repairs(hass, entry, vins, vehicle_metadata)

    @callback
    def _handle_metadata_update() -> None:
        """Re-evaluate vehicle repair issues when metadata changes."""
        data = metadata_coordinator.data
        if not data:
            return
        _async_update_vehicle_repairs(hass, entry, vins, data["vehicles"])

    entry.async_on_unload(
        metadata_coordinator.async_add_listener(_handle_metadata_update)
    )


def hacs_migrate_subentry_entities(
    hass: HomeAssistant, entry: TeslemetryConfigEntry
) -> None:
    """Reparent legacy config-subentry entities and devices onto the main entry.

    HACS-only standing migration (see AGENTS.md for its scope and retirement).
    Installs that ran the old entity-parenting layout own every vehicle and
    energy entity and device under a generated config subentry; the current
    model keeps cloud entities and devices on the main entry and uses subentries
    only as optional local-control holders. Move every registry record still
    bound to one of this entry's subentries back onto the main entry, leaving
    unique IDs, entity IDs, and the subentry objects and their pairing
    credentials untouched. Idempotent.
    """
    subentry_ids = set(entry.subentries)
    if not subentry_ids:
        return

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    # Clear each entity's subentry before moving its device: the registry
    # cascade-deletes an entity left pointing at the subentry its device moves
    # off, which would detach the user's recorder history behind a new entity ID.
    for reg_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if reg_entry.config_subentry_id in subentry_ids:
            entity_registry.async_update_entity(
                reg_entry.entity_id, config_subentry_id=None
            )

    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if hasattr(device, "config_subentry_id"):
            # Single-owner device registry (core dev): one move to the main entry.
            if device.config_subentry_id in subentry_ids:
                device_registry.async_update_device(
                    device.id, new_config_subentry_id=None
                )
            continue
        # Multi-owner device registry (stable core): add the main entry first,
        # then drop each stale membership. A combined add+remove, or a lone
        # remove of a device's only subentry, would delete the device.
        stale = (
            device.config_entries_subentries.get(entry.entry_id, set()) & subentry_ids
        )
        if not stale:
            continue
        device_registry.async_update_device(
            device.id,
            add_config_entry_id=entry.entry_id,
            add_config_subentry_id=None,
        )
        for subentry_id in stale:
            device_registry.async_update_device(
                device.id,
                remove_config_entry_id=entry.entry_id,
                remove_config_subentry_id=subentry_id,
            )


# Auto-created (unpaired) holder subentries carry only their identity key.
# Pairing adds credential keys (a Bluetooth address for a vehicle, the gateway
# host/password for an energy site), whose presence marks a holder configured.
# These literals are the on-disk subentry wire format written by older builds.
_HOLDER_IDENTITY_KEYS: Final[dict[str, str]] = {
    "vehicle": "vin",
    "energy_site": "site_id",
}


def hacs_remove_empty_holder_subentries(
    hass: HomeAssistant, entry: TeslemetryConfigEntry
) -> None:
    """Remove auto-created local-control holder subentries that were never paired.

    HACS-only forward cleanup that rides main. Older builds created a vehicle and
    battery-energy holder for every product whether or not the user paired local
    control; the current model creates one only when pairing completes, so those
    unpaired holders are leftover empty configuration. Remove a holder only when
    it carries no pairing credentials and owns no registry record, leaving every
    configured holder and its credentials in place. Must run after
    hacs_migrate_subentry_entities, which reparents any record a holder still
    owned. Idempotent.
    """
    subentries = entry.subentries
    if not subentries:
        return

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    # A holder that still owns any registry record is kept, even after
    # normalization: assert emptiness rather than assume it.
    owning: set[str] = set()
    for reg_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if reg_entry.config_subentry_id is not None:
            owning.add(reg_entry.config_subentry_id)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if hasattr(device, "config_subentry_id"):
            # Single-owner device registry (core dev).
            if device.config_subentry_id is not None:
                owning.add(device.config_subentry_id)
            continue
        # Multi-owner device registry (stable core).
        owning |= {
            subentry_id
            for subentry_id in device.config_entries_subentries.get(
                entry.entry_id, set()
            )
            if subentry_id is not None
        }

    for subentry_id, subentry in list(subentries.items()):
        identity_key = _HOLDER_IDENTITY_KEYS.get(subentry.subentry_type)
        if identity_key is None:
            continue
        if subentry_id in owning:
            continue
        if set(subentry.data) - {identity_key}:
            continue
        hass.config_entries.async_remove_subentry(entry, subentry_id)


def beta_migration_fix(hass: HomeAssistant, entry: TeslemetryConfigEntry) -> None:
    """Fix beta migration issues."""
    # This is needed to migrate beta users to the new OAuth credential system.
    if "auth_implementation" not in entry.data:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, "auth_implementation": DOMAIN},
        )


def _async_setup_option_reload(
    hass: HomeAssistant, entry: TeslemetryConfigEntry, ship_logs: bool
) -> None:
    """Reload only when the ClickStack log-shipping option actually changes.

    An entry update fires for any change (a token refresh, a subentry add or
    remove); reloading on every one stacks redundant reloads. Only a change to
    the shipping option needs a reload, to re-derive the shipper force-count.
    """
    shipping = ship_logs

    async def _handle_update(
        hass: HomeAssistant, updated_entry: TeslemetryConfigEntry
    ) -> None:
        nonlocal shipping
        updated = updated_entry.options.get(CONF_SHIP_LOGS_TO_CLICKSTACK, False)
        if updated == shipping:
            return
        shipping = updated
        await hass.config_entries.async_reload(updated_entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_handle_update))


def _subentry_snapshot(
    entry: TeslemetryConfigEntry,
) -> dict[str, tuple[str, tuple[tuple[str, Any], ...]]]:
    """Snapshot each subentry's type and data for change detection.

    A vehicle subentry carries its Bluetooth address and an energy-site subentry
    its local gateway credentials; both drive which backend a product routes
    through, so a data edit (reconfigure) matters as much as an add or remove.
    """
    return {
        subentry_id: (
            subentry.subentry_type,
            tuple(sorted(subentry.data.items())),
        )
        for subentry_id, subentry in entry.subentries.items()
    }


def _setup_subentry_change_reload(
    hass: HomeAssistant, entry: TeslemetryConfigEntry
) -> None:
    """Reload the entry when a vehicle or energy-site subentry changes.

    Covers both BLE-paired vehicle subentries and local-control energy-site
    subentries: adding, removing, or editing one must re-run setup so the product
    starts, stops, or re-points its local backend. Entry-level updates that leave
    every subentry untouched (a token refresh, an options change) never reload.
    """
    known = _subentry_snapshot(entry)

    async def _handle_update(
        hass: HomeAssistant, updated_entry: TeslemetryConfigEntry
    ) -> None:
        nonlocal known
        current = _subentry_snapshot(updated_entry)
        if current != known:
            hass.config_entries.async_schedule_reload(updated_entry.entry_id)
        # Track the latest snapshot so further updates before the reload runs
        # (e.g. a token refresh) do not re-schedule it off the same change.
        known = current

    entry.async_on_unload(entry.add_update_listener(_handle_update))


def _ble_address_for_vin(entry: TeslemetryConfigEntry, vin: str) -> str | None:
    """Return the paired Bluetooth address for a vehicle, if one was added."""
    for subentry in entry.subentries.values():
        if (
            subentry.subentry_type == SUBENTRY_TYPE_VEHICLE
            and subentry.data.get(CONF_VIN) == vin
        ):
            return subentry.data.get(CONF_ADDRESS)
    return None


async def _async_resolve_vehicle_api(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    vin: str,
    cloud_vehicle: Vehicle,
) -> Vehicle | VehicleRouter:
    """Return the API a vehicle's platforms should call.

    An unpaired vehicle (its subentry carries no BLE ``address``) uses the cloud
    Vehicle. A paired vehicle always gets a VehicleRouter, whether or not it is
    in range right now: the router's health check re-reads Home Assistant's
    Bluetooth discovery cache on every command, so a vehicle that drives away
    and comes back resumes local routing on its own. A vehicle out of range is
    skipped by the health check, sending the command straight to cloud without
    attempting Bluetooth.

    The router's ``primary`` is the direct BLE client local data readers take
    unsolicited broadcasts from, without going through the router, for which
    cloud fallback is forbidden on BLE-sourced state.
    """
    address = _ble_address_for_vin(entry, vin)
    if not address:
        return cloud_vehicle

    parent = await async_get_ble_parent(hass)
    # verify + raise_unconfirmed=False so an ambiguous BLE timeout resolves as a
    # verified or best-effort success instead of re-sending to cloud, which
    # would double-execute a non-idempotent command. keepalive_interval=None so
    # command-only use does not hold the link open and keep the car awake.
    bluetooth_vehicle = parent.vehicles.createBluetooth(
        vin,
        confirmation="verify",
        raise_unconfirmed=False,
        keepalive_interval=None,
    )

    @callback
    def _in_range() -> bool:
        """Report whether the vehicle is currently reachable over Bluetooth."""
        device = async_ble_device_from_address(hass, address, connectable=True)
        if device is None:
            return False
        # The library does not pass establish_connection a ble_device_callback,
        # so nothing else refreshes the handle; do it here, the one moment it is
        # known fresh and a connect may immediately follow.
        bluetooth_vehicle.set_device(device)
        return True

    return VehicleRouter(bluetooth_vehicle, cloud_vehicle, health=_in_range)


def _find_energy_subentry_id(entry: TeslemetryConfigEntry, site_id: int) -> str | None:
    """Return the user-added local-control subentry id bound to site_id, if any."""
    return next(
        (
            subentry.subentry_id
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_ENERGY_SITE
            and subentry.unique_id == str(site_id)
        ),
        None,
    )


def _remove_stale_subentries(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    subentry_type: str,
    current_subentry_ids: set[str],
) -> None:
    """Remove subentries of the given type with no matching product."""
    for subentry in list(entry.subentries.values()):
        if (
            subentry.subentry_type == subentry_type
            and subentry.subentry_id not in current_subentry_ids
        ):
            LOGGER.debug("Removing stale subentry %s", subentry.subentry_id)
            hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)


def _prune_energy_subentries(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    scopes: list[Scope],
    products: list[dict[str, Any]],
) -> None:
    """Remove energy-site subentries whose site is no longer on the account."""
    if Scope.ENERGY_DEVICE_DATA not in scopes:
        return
    # Prune against the raw product inventory, not the access-filtered energysites
    # list: a site can report access:false transiently while still on the account,
    # and pruning on that flag would delete a live gateway's paired credentials.
    product_site_ids = {
        str(product["energy_site_id"])
        for product in products
        if "energy_site_id" in product
    }
    _remove_stale_subentries(
        hass,
        entry,
        SUBENTRY_TYPE_ENERGY_SITE,
        {
            subentry.subentry_id
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_ENERGY_SITE
            and subentry.unique_id in product_site_ids
        },
    )


async def _async_get_rsa_key_pem(hass: HomeAssistant) -> bytes:
    """Return the integration's RSA private key PEM, generating it if needed."""
    pem: bytes | None = hass.data.get(RSA_PARENT_KEY)
    if pem is None:
        path = hass.config.path(POWERWALL_KEY_FILE)
        await Teslemetry(
            session=async_get_clientsession(hass), access_token=""
        ).get_rsa_private_key(path)
        pem = await hass.async_add_executor_job(Path(path).read_bytes)
        hass.data[RSA_PARENT_KEY] = pem
    return pem


# PowerwallError covers aiopowerwall failures (a bad key PEM raises its
# PowerwallAuthenticationError subclass); key I/O and parsing raise OSError and
# ValueError.
_LOCAL_CONTROL_ERRORS: Final = (OSError, ValueError, PowerwallError)


async def _async_resolve_local_control(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    battery: bool,
    site_id: int,
    site_name: str,
    cloud_energy_site: EnergySite,
) -> tuple[bool, str | None, EnergySite | EnergySiteRouter]:
    """Resolve opt-in local control for an energy site."""
    issue_id = local_control_issue_id(entry, site_id)
    # Only a battery/Powerwall (TEDAPI) gateway can pair for local control;
    # solar-only and wall-connector-only sites cannot.
    if not battery:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return False, None, cloud_energy_site
    subentry_id = _find_energy_subentry_id(entry, site_id)
    if subentry_id is None:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return True, None, cloud_energy_site
    # Local control is opt-in per site; a failure resolving one site's local
    # gateway (key I/O, key parsing, or client construction) must not tear down
    # the whole integration, so isolate it to this site: fall back to cloud
    # control and raise a repair so the user knows local control is inactive and
    # this site is still spending cloud command credits.
    try:
        api = await _async_resolve_energy_site_api(
            hass, entry, subentry_id, cloud_energy_site
        )
    except _LOCAL_CONTROL_ERRORS:
        LOGGER.warning(
            "Failed to set up local control for energy site %s; "
            "falling back to cloud control",
            site_id,
            exc_info=True,
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="local_control_unavailable",
            translation_placeholders={"site": site_name},
            learn_more_url=f"https://teslemetry.com/console/energy/{site_id}",
        )
        return True, subentry_id, cloud_energy_site
    ir.async_delete_issue(hass, DOMAIN, issue_id)
    return True, subentry_id, api


async def _async_resolve_energy_site_api(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    subentry_id: str,
    cloud_energy_site: EnergySite,
) -> EnergySite | EnergySiteRouter:
    """Return the API an energy site's platforms should call."""
    data = entry.subentries[subentry_id].data
    host = data.get(CONF_HOST)
    password = data.get(CONF_PASSWORD)
    if not host or not password:
        return cloud_energy_site

    key_pem = await _async_get_rsa_key_pem(hass)
    powerwall_client = PowerwallClient(
        host=host,
        gateway_password=password,
        rsa_private_key_pem=key_pem,
        session=async_get_clientsession(hass),
    )
    local_energy_site = PowerwallEnergySite(powerwall_client)
    return EnergySiteRouter(local_energy_site, cloud_energy_site)


async def async_setup_entry(hass: HomeAssistant, entry: TeslemetryConfigEntry) -> bool:
    """Set up Teslemetry config."""

    if "token" not in entry.data:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="token_data_malformed",
        )

    # Normalize legacy config-subentry records before inventory, stale cleanup,
    # or platform forwarding so a temporarily inaccessible product is still moved
    # onto the main entry and never cascade-deleted by later pruning.
    hacs_migrate_subentry_entities(hass, entry)

    # Drop unpaired auto-created holders older builds left behind, strictly after
    # reparenting so a holder that still owned records is never removed.
    hacs_remove_empty_holder_subentries(hass, entry)

    # Opt-in ClickStack log shipping (HACS-only). The uid is already known
    # from config flow (entry.unique_id). Shipping is authorized solely by
    # the durable per-entry option, which survives restarts, checked
    # per-record in logship.py.
    ship_logs = entry.options.get(CONF_SHIP_LOGS_TO_CLICKSTACK, False)
    logship = async_get_or_create_logship(hass, entry.unique_id or "unknown")
    await logship.async_acquire(force=ship_logs)
    entry.async_on_unload(partial(logship.async_release, force=ship_logs))
    _async_setup_option_reload(hass, entry, ship_logs)

    try:
        beta_migration_fix(hass, entry)
        implementation = await async_get_config_entry_implementation(hass, entry)
    except ImplementationUnavailableError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="oauth_implementation_not_available",
        ) from err

    oauth_session = OAuth2Session(hass, entry, implementation)

    session = async_get_clientsession(hass)

    # Create API connection
    access_token = partial(_get_access_token, oauth_session)
    teslemetry = Teslemetry(
        session=session,
        access_token=access_token,
    )
    # Fetch metadata through the coordinator so it owns the data the platforms
    # read at setup (e.g. per-vehicle config for seat heaters).
    metadata_coordinator = TeslemetryMetadataCoordinator(hass, entry, teslemetry)
    try:
        products_call, _ = await asyncio.gather(
            teslemetry.products(),
            metadata_coordinator.async_config_entry_first_refresh(),
        )
    except InvalidToken as e:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed_invalid_token",
        ) from e
    except LoginRequired as e:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed_login_required",
        ) from e
    except SubscriptionRequired as e:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed_subscription_required",
        ) from e
    except TeslaFleetError as e:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="not_ready_api_error",
        ) from e

    metadata = metadata_coordinator.data
    scopes = metadata["scopes"]
    region = metadata["region"]
    vehicle_metadata = metadata["vehicles"]
    energy_site_metadata = metadata["energy_sites"]
    products = products_call["response"]

    device_registry = dr.async_get(hass)

    # Create array of classes
    vehicles: list[TeslemetryVehicleData] = []
    energysites: list[TeslemetryEnergyData] = []

    # Create the stream (created lazily for the first eligible vehicle or
    # energy site, so energy-only accounts still open the account stream)
    stream: TeslemetryStream | None = None

    def create_stream() -> TeslemetryStream:
        return TeslemetryStream(
            session,
            access_token,
            server=f"{region.lower()}.teslemetry.com",
            parse_timestamp=True,
            manual=True,
            topics=STREAM_TOPICS,
        )

    # Remember each device identifier we create
    current_devices: set[tuple[str, str]] = set()

    # Track known devices for dynamic discovery (based on metadata access state)
    known_vins, known_site_ids = _get_subscribed_ids_from_metadata(metadata)

    for product in products:
        if (
            "vin" in product
            and vehicle_metadata.get(product["vin"], {}).get("access")
            and Scope.VEHICLE_DEVICE_DATA in scopes
        ):
            vin = product["vin"]
            current_devices.add((DOMAIN, vin))

            # Create stream if required (for first vehicle)
            if not stream:
                stream = create_stream()

            # Remove the protobuff 'cached_data' that we do not use to save memory
            product.pop("cached_data", None)
            vehicle = teslemetry.vehicles.create(vin)
            coordinator = TeslemetryVehicleDataCoordinator(
                hass, entry, vehicle, product
            )
            firmware = vehicle_metadata[vin].get("firmware")
            device = DeviceInfo(
                identifiers={(DOMAIN, vin)},
                manufacturer="Tesla",
                configuration_url=f"https://teslemetry.com/console/vehicle/{vin}",
                name=product["display_name"],
                model=vehicle.model,
                model_id=vin[3],
                serial_number=vin,
                sw_version=firmware,
            )

            poll = vehicle_metadata[vin].get("polling", False)

            entry.async_on_unload(
                stream.async_add_listener(
                    create_handle_vehicle_stream(vin, coordinator),
                    {"vin": vin},
                )
            )
            stream_vehicle = stream.get_vehicle(vin)

            # Route commands through Bluetooth first when the user has added this
            # vehicle over Bluetooth; otherwise this returns the plain cloud
            # Vehicle.
            vehicle_api = await _async_resolve_vehicle_api(
                hass,
                entry,
                vin,
                vehicle,
            )

            # A paired vehicle's router exposes the direct BLE client as its
            # primary; local data reads take broadcasts from it, never the router.
            ble: TeslemetryBLEDataManager | None = None
            if isinstance(vehicle_api, VehicleRouter):
                ble = TeslemetryBLEDataManager(
                    hass, vehicle_api.primary, stream_vehicle, vin
                )
                ble.async_start()
                entry.async_on_unload(ble.async_stop)

            vehicles.append(
                TeslemetryVehicleData(
                    api=vehicle_api,
                    config_entry=entry,
                    coordinator=coordinator,
                    poll=poll,
                    stream=stream,
                    stream_vehicle=stream_vehicle,
                    vin=vin,
                    firmware=firmware or "Unknown",
                    device=device,
                    ble=ble,
                )
            )

        elif (
            "energy_site_id" in product
            and Scope.ENERGY_DEVICE_DATA in scopes
            and energy_site_metadata.get(str(product["energy_site_id"]), {}).get(
                "access"
            )
        ):
            site_id = product["energy_site_id"]

            battery = product["components"]["battery"]
            powerwall = battery or product["components"]["solar"]
            wall_connector = "wall_connectors" in product["components"]
            if not powerwall and not wall_connector:
                LOGGER.debug(
                    "Skipping Energy Site %s as it has no components",
                    site_id,
                )
                continue

            # Create stream if required (for first energy site)
            if not stream:
                stream = create_stream()

            current_devices.add((DOMAIN, str(site_id)))
            if wall_connector:
                current_devices |= {
                    (DOMAIN, c["din"]) for c in product["components"]["wall_connectors"]
                }

            energy_site = teslemetry.energySites.create(site_id)
            site_name = product.get("site_name", "Energy Site")
            device = DeviceInfo(
                identifiers={(DOMAIN, str(site_id))},
                manufacturer="Tesla",
                configuration_url=f"https://teslemetry.com/console/energy/{site_id}",
                name=site_name,
                serial_number=str(site_id),
            )

            (
                live_coordinator,
                info_coordinator,
                history_coordinator,
                live_status,
            ) = await _async_setup_energy_site(
                hass,
                entry,
                stream,
                energy_site,
                product,
                site_id,
                powerwall,
            )

            # Local control is opt-in per site: a subentry only exists once the
            # user pairs one through the "Add local energy site" flow. Resolving
            # it here, at the call site, keeps the streaming helper independent of
            # local-control setup order.
            (
                can_local_control,
                subentry_id,
                energy_site_api,
            ) = await _async_resolve_local_control(
                hass, entry, bool(battery), site_id, site_name, energy_site
            )

            # A paired site gets a second, local-first live coordinator for the
            # Powerwall-supported live keys; the cloud live coordinator keeps
            # serving the cloud-only live entities. Seed the local one from an
            # independent copy so the cloud coordinator's in-place wall-connector
            # normalisation does not corrupt the shared snapshot.
            live_local_coordinator = (
                TeslemetryEnergySiteLiveLocalCoordinator(
                    hass, entry, energy_site_api, deepcopy(live_status)
                )
                if isinstance(energy_site_api, EnergySiteRouter)
                and isinstance(live_status, dict)
                else None
            )

            energysites.append(
                TeslemetryEnergyData(
                    api=energy_site_api,
                    live_coordinator=live_coordinator,
                    live_local_coordinator=live_local_coordinator,
                    info_coordinator=info_coordinator,
                    history_coordinator=history_coordinator,
                    id=site_id,
                    device=device,
                    can_local_control=can_local_control,
                    subentry_id=subentry_id,
                )
            )

    # Run all first refreshes
    await asyncio.gather(
        *(async_setup_stream(hass, entry, vehicle) for vehicle in vehicles),
        *(
            vehicle.coordinator.async_config_entry_first_refresh()
            for vehicle in vehicles
            if vehicle.poll
        ),
        *(
            energysite.info_coordinator.async_config_entry_first_refresh()
            for energysite in energysites
        ),
    )

    # Setup energy devices with models, versions, and listeners
    for energysite in energysites:
        async_setup_energy_device(hass, entry, energysite, device_registry)

    # Remove devices that are no longer present
    for device_entry in dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    ):
        if not any(
            identifier in current_devices for identifier in device_entry.identifiers
        ):
            LOGGER.debug("Removing stale device %s", device_entry.id)
            device_registry.async_remove_device(device_entry.id)

    _prune_energy_subentries(hass, entry, scopes, products)

    entry.runtime_data = TeslemetryData(
        vehicles=vehicles,
        energysites=energysites,
        scopes=scopes,
        stream=stream,
        metadata_coordinator=metadata_coordinator,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload when a vehicle or energy-site subentry is added, removed, or edited
    # so the affected product starts, stops, or re-points its local backend (BLE
    # for a vehicle, the Powerwall gateway for an energy site).
    _setup_subentry_change_reload(hass, entry)

    _setup_dynamic_discovery(
        hass,
        entry,
        metadata_coordinator,
        known_vins,
        known_site_ids,
    )

    _setup_vehicle_repairs(
        hass,
        entry,
        metadata_coordinator,
        {vehicle.vin for vehicle in vehicles},
        vehicle_metadata,
    )

    if stream:
        entry.async_on_unload(stream.close)
        entry.async_on_unload(
            stream.listen_Credits(partial(async_handle_credits, hass, entry))
        )
        # The stream is the only freshness signal for the energy coordinators, so
        # a dropped connection must mark their entities unavailable rather than
        # leaving stale live/info/tariff data available indefinitely.
        if energysites:
            entry.async_on_unload(
                stream.async_add_connection_listener(
                    create_handle_energy_stream_connection(energysites)
                )
            )
        entry.async_create_background_task(hass, stream.listen(), "Teslemetry Stream")

    return True


def create_handle_energy_stream_connection(
    energysites: list[TeslemetryEnergyData],
) -> Callable[[bool], None]:
    """Create a stream connection listener for the energy coordinators."""

    @callback
    def handle_connection(connected: bool) -> None:
        """Fail stream-driven energy coordinators while the stream is down.

        Each subsequent streamed document restores its coordinator via
        async_set_updated_data, so no reload is required on reconnect.
        """
        if connected:
            return
        error = UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="stream_disconnected",
        )
        for energysite in energysites:
            if energysite.live_coordinator is not None:
                energysite.live_coordinator.async_set_update_error(error)
            energysite.info_coordinator.async_set_update_error(error)

    return handle_connection


async def _async_setup_energy_site(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    stream: TeslemetryStream,
    energy_site: EnergySite,
    product: dict[str, Any],
    site_id: int,
    powerwall: Any,
) -> tuple[
    TeslemetryEnergySiteLiveCoordinator | None,
    TeslemetryEnergySiteInfoCoordinator,
    TeslemetryEnergyHistoryCoordinator | None,
    Any,
]:
    """Cold-read live status, build the energy coordinators, and register listeners.

    The cold-read ``live_status`` is returned so a paired site can seed a
    local-first live coordinator from an independent copy of the same snapshot.
    """
    # The stream has no ready boundary, so keep a deterministic REST cold read
    # for setup auth/error handling before switching to listener-driven updates.
    try:
        live_status = (await energy_site.live_status())["response"]
    except InvalidToken as e:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed_invalid_token",
        ) from e
    except LoginRequired as e:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed_login_required",
        ) from e
    except SubscriptionRequired as e:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed_subscription_required",
        ) from e
    except Forbidden as e:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed_invalid_token",
        ) from e
    except TeslaFleetError as e:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="not_ready_api_error",
        ) from e

    # Snapshot the cold read before the cloud coordinator normalises its wall
    # connectors in place, so a paired site's local coordinator seeds from clean
    # data rather than an already-indexed snapshot.
    live_status_snapshot = (
        deepcopy(live_status) if isinstance(live_status, dict) else live_status
    )
    live_coordinator = (
        TeslemetryEnergySiteLiveCoordinator(hass, entry, energy_site, live_status)
        if isinstance(live_status, dict)
        else None
    )
    info_coordinator = TeslemetryEnergySiteInfoCoordinator(
        hass, entry, energy_site, product
    )

    # Register before stream.listen() so the opening snapshot cannot be missed.
    stream_energysite = stream.get_energysite(site_id)
    if live_coordinator is not None:
        entry.async_on_unload(
            stream_energysite.listen_LiveStatus(live_coordinator.handle_stream_update)
        )
    entry.async_on_unload(
        stream_energysite.listen_SiteInfo(info_coordinator.handle_site_info)
    )
    entry.async_on_unload(
        stream_energysite.listen_TariffContentV2(
            info_coordinator.handle_tariff_content_v2
        )
    )

    history_coordinator = (
        TeslemetryEnergyHistoryCoordinator(hass, entry, energy_site)
        if powerwall
        else None
    )

    return live_coordinator, info_coordinator, history_coordinator, live_status_snapshot


async def async_unload_entry(hass: HomeAssistant, entry: TeslemetryConfigEntry) -> bool:
    """Unload Teslemetry Config."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # The repair issue is not tied to the config entry, so clear it here (this
        # also runs on removal) once the entry has actually unloaded. Gate on a
        # successful unload so a FAILED_UNLOAD entry keeps its still-relevant repair.
        ir.async_delete_issue(hass, DOMAIN, insufficient_credits_issue_id(entry))
        # Release any on-demand Bluetooth link a command opened so it is not left
        # connected across a reload. Only once the platforms actually unloaded -
        # otherwise the entry stays loaded and its backends must keep working.
        for vehicle in entry.runtime_data.vehicles:
            if isinstance(vehicle.api, VehicleRouter):
                try:
                    async with asyncio.timeout(BLE_DISCONNECT_TIMEOUT):
                        await vehicle.api.primary.disconnect()
                except (BleakError, TeslaFleetError, TimeoutError) as err:
                    LOGGER.debug(
                        "Error disconnecting Bluetooth for %s: %s", vehicle.vin, err
                    )
    return unload_ok


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: TeslemetryConfigEntry
) -> bool:
    """Migrate config entry."""

    if config_entry.version == 1:
        access_token = config_entry.data[CONF_ACCESS_TOKEN]
        session = async_get_clientsession(hass)

        # Convert legacy access token to OAuth tokens using migrate endpoint
        try:
            data = await Teslemetry(session, access_token).migrate_to_oauth(
                CLIENT_ID, hass.config.location_name
            )
        except (ClientError, TypeError) as e:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed_migration",
            ) from e

        # The migrate grant only accepts the legacy static client_id, so that
        # client must back auth_implementation, not a dynamically registered
        # one. Import it only after migration succeeds, otherwise a failed
        # migration would leave a stale credential that permanently skips DCR.
        await async_import_client_credential(
            hass, DOMAIN, ClientCredential(CLIENT_ID, "", name="Teslemetry")
        )

        # Add auth_implementation for OAuth2 flow compatibility
        data["auth_implementation"] = DOMAIN

        return hass.config_entries.async_update_entry(
            config_entry,
            data=data,
            version=2,
        )
    return True


def create_handle_vehicle_stream(
    vin: str, coordinator: TeslemetryVehicleDataCoordinator
) -> Callable[[dict[str, Any]], None]:
    """Create a handle vehicle stream function."""

    def handle_vehicle_stream(data: dict[str, Any]) -> None:
        """Handle vehicle data from the stream."""
        if "vehicle_data" in data:
            LOGGER.debug("Streaming received vehicle data from %s", vin)
            coordinator.async_set_updated_data(flatten(data["vehicle_data"]))
        elif "state" in data:
            LOGGER.debug("Streaming received state from %s", vin)
            coordinator.data["state"] = data["state"]
            coordinator.async_set_updated_data(coordinator.data)

    return handle_vehicle_stream


def async_setup_energy_device(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    energysite: TeslemetryEnergyData,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Set up energy device with models, versions, and listeners."""
    data = energysite.info_coordinator.data
    models = set()
    for component in (
        *data.get("components_gateways", []),
        *data.get("components_batteries", []),
    ):
        if (part_name := component.get("part_name")) and part_name != "Unknown":
            models.add(part_name)
    if models:
        energysite.device["model"] = ", ".join(sorted(models))

    if version := data.get("version"):
        energysite.device["sw_version"] = version

    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, **energysite.device
    )

    entry.async_on_unload(
        energysite.info_coordinator.async_add_listener(
            create_energy_info_listener(
                hass, energysite.id, entry.entry_id, energysite.info_coordinator
            )
        )
    )


async def async_setup_stream(
    hass: HomeAssistant, entry: TeslemetryConfigEntry, vehicle: TeslemetryVehicleData
) -> None:
    """Set up the stream for a vehicle."""
    await vehicle.stream_vehicle.get_config()
    entry.async_create_background_task(
        hass,
        vehicle.stream_vehicle.prefer_typed(True),
        f"Prefer typed for {vehicle.vin}",
    )

    entry.async_on_unload(
        vehicle.stream_vehicle.listen_Version(
            create_vehicle_streaming_listener(hass, vehicle.vin, entry.entry_id)
        )
    )


def create_vehicle_streaming_listener(
    hass: HomeAssistant, vin: str, config_entry_id: str
) -> Callable[[str | None], None]:
    """Create a listener for vehicle streaming version updates."""

    def handle_version(value: str | None) -> None:
        """Handle version update from stream."""
        if value is not None:
            # Remove build from version (e.g., "2024.44.25 abc123" -> "2024.44.25")
            sw_version = value.split(" ")[0]
            async_update_device_sw_version(hass, vin, config_entry_id, sw_version)

    return handle_version


def create_energy_info_listener(
    hass: HomeAssistant,
    site_id: int,
    config_entry_id: str,
    coordinator: TeslemetryEnergySiteInfoCoordinator,
) -> Callable[[], None]:
    """Create a listener for energy site info coordinator updates."""

    def handle_update() -> None:
        """Handle coordinator update."""
        if version := coordinator.data.get("version"):
            async_update_device_sw_version(hass, str(site_id), config_entry_id, version)

    return handle_update
