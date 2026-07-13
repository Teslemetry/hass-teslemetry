"""Test the HACS-only subentry back-migration and per-path energy migration.

Covers the standing ``hacs_migrate_subentry_entities`` back-migration plus the
per-upgrade-path behavior of the v6.0.4 local-Powerwall re-introduction: fresh
install, v6.0.2/6.0.3 -> v6.0.4, and the direct v6.0.0/6.0.1 -> v6.0.4 upgrade
that preserves and reuses the old local gateway pairing.
"""

from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from tesla_fleet_api.tesla import EnergySiteRouter
from tesla_fleet_api.teslemetry import EnergySite

from homeassistant.components.teslemetry import hacs_migrate_subentry_entities
from homeassistant.components.teslemetry.const import (
    CONF_SITE_ID,
    CONF_VIN,
    DOMAIN,
    SUBENTRY_TYPE_ENERGY_SITE,
    SUBENTRY_TYPE_VEHICLE,
)
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from . import mock_config_entry

from tests.common import MockConfigEntry

VIN = "LRW3F7EK4NC700000"
SITE_ID = "123456789"

# The account's mocked products carry this Powerwall-capable energy site, so a
# subentry whose unique_id matches it is re-found and merged during setup.
POWERWALL_SITE_ID = 123456
HOST = "192.168.91.1"
PASSWORD = "abcde"

# A real (undersized, for speed) RSA key: aiopowerwall's PowerwallClient parses
# the PEM at construction, so the paired-path setup needs a valid key.
_TEST_RSA_KEY_PEM = rsa.generate_private_key(
    public_exponent=65537, key_size=1024
).private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
)


def _entry_with_option1_subentries() -> MockConfigEntry:
    """Return an entry shaped like a v6.0.0/6.0.1 install (Option-1)."""
    entry = mock_config_entry()
    return MockConfigEntry(
        domain=entry.domain,
        version=entry.version,
        minor_version=entry.minor_version,
        unique_id=entry.unique_id,
        data=dict(entry.data),
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_VEHICLE,
                unique_id=VIN,
                title="Test Vehicle",
                data={CONF_VIN: VIN},
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
                unique_id=SITE_ID,
                title="Test Energy Site",
                data={"site_id": SITE_ID},
            ),
        ],
    )


def _seed_subentry_device_and_entity(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    subentry_id: str,
    identifier: str,
    unique_id: str,
) -> tuple[str, str]:
    """Parent a device and an entity under a subentry, Option-1 style."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id=subentry_id,
        identifiers={(DOMAIN, identifier)},
    )
    entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        unique_id,
        config_entry=entry,
        config_subentry_id=subentry_id,
        device_id=device.id,
    )
    return device.id, entity.entity_id


async def test_migrate_reparents_entities_and_devices(hass: HomeAssistant) -> None:
    """Entities and devices under a subentry move back onto the main entry."""
    entry = _entry_with_option1_subentries()
    entry.add_to_hass(hass)

    vehicle_subentry_id = entry.get_subentries_of_type(SUBENTRY_TYPE_VEHICLE)[
        0
    ].subentry_id
    energy_subentry_id = entry.get_subentries_of_type(SUBENTRY_TYPE_ENERGY_SITE)[
        0
    ].subentry_id

    vehicle_device_id, vehicle_entity_id = _seed_subentry_device_and_entity(
        hass, entry, vehicle_subentry_id, VIN, f"{VIN}_battery_level"
    )
    energy_device_id, energy_entity_id = _seed_subentry_device_and_entity(
        hass, entry, energy_subentry_id, SITE_ID, f"{SITE_ID}_solar_power"
    )

    hacs_migrate_subentry_entities(hass, entry)

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    # Nothing is deleted; both cloud entities survive on the main entry.
    for entity_id in (vehicle_entity_id, energy_entity_id):
        reg_entry = entity_registry.async_get(entity_id)
        assert reg_entry is not None
        assert reg_entry.config_subentry_id is None
        assert reg_entry.config_entry_id == entry.entry_id

    for device_id in (vehicle_device_id, energy_device_id):
        device = device_registry.async_get(device_id)
        assert device is not None
        assert device.config_entries_subentries[entry.entry_id] == {None}


async def test_migrate_is_idempotent(hass: HomeAssistant) -> None:
    """A second run over already-migrated state changes nothing."""
    entry = _entry_with_option1_subentries()
    entry.add_to_hass(hass)

    vehicle_subentry_id = entry.get_subentries_of_type(SUBENTRY_TYPE_VEHICLE)[
        0
    ].subentry_id
    _, vehicle_entity_id = _seed_subentry_device_and_entity(
        hass, entry, vehicle_subentry_id, VIN, f"{VIN}_battery_level"
    )

    hacs_migrate_subentry_entities(hass, entry)
    entity_registry = er.async_get(hass)
    first = entity_registry.async_get(vehicle_entity_id)

    hacs_migrate_subentry_entities(hass, entry)
    second = entity_registry.async_get(vehicle_entity_id)

    assert first == second
    assert second.config_subentry_id is None


async def test_migrate_no_subentries_is_noop(hass: HomeAssistant) -> None:
    """An entry with no subentries (fresh v6.0.2 install) is untouched."""
    entry = mock_config_entry()
    entry.add_to_hass(hass)

    entity_registry = er.async_get(hass)
    entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{VIN}_battery_level",
        config_entry=entry,
    )

    hacs_migrate_subentry_entities(hass, entry)

    survived = entity_registry.async_get(entity.entity_id)
    assert survived is not None
    assert survived.config_subentry_id is None


async def test_fresh_install_creates_unpaired_config_holder(
    hass: HomeAssistant,
) -> None:
    """Fresh v6.0.4 install: a Powerwall site gets an unpaired cloud config-holder."""
    entry = mock_config_entry()
    entry.add_to_hass(hass)

    with patch("homeassistant.components.teslemetry.PLATFORMS", []):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    energy_subentries = entry.get_subentries_of_type(SUBENTRY_TYPE_ENERGY_SITE)
    assert len(energy_subentries) == 1
    data = energy_subentries[0].data
    # Unpaired: only the site id, no local gateway host/password yet.
    assert data[CONF_SITE_ID] == POWERWALL_SITE_ID
    assert CONF_HOST not in data
    assert CONF_PASSWORD not in data
    # Cloud energy stays fully functional; routing is off until pairing.
    api = entry.runtime_data.energysites[0].api
    assert isinstance(api, EnergySite)
    assert not isinstance(api, EnergySiteRouter)


async def test_upgrade_from_v603_adds_config_holder_without_disturbing_cloud(
    hass: HomeAssistant,
) -> None:
    """v6.0.2/6.0.3 -> v6.0.4: vehicle pairing-holder kept, fresh energy CH added.

    A v6.0.3 install carries only a vehicle pairing-holder and cloud energy on
    the parent (no energy subentry). Setup must leave the vehicle subentry
    untouched, create a fresh unpaired energy config-holder, and keep cloud
    energy (no local routing).
    """
    base = mock_config_entry()
    entry = MockConfigEntry(
        domain=base.domain,
        version=base.version,
        minor_version=base.minor_version,
        unique_id=base.unique_id,
        data=dict(base.data),
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_VEHICLE,
                unique_id=VIN,
                title="Test Vehicle",
                data={CONF_VIN: VIN},
            )
        ],
    )
    entry.add_to_hass(hass)
    vehicle_subentry_id = entry.get_subentries_of_type(SUBENTRY_TYPE_VEHICLE)[
        0
    ].subentry_id

    with patch("homeassistant.components.teslemetry.PLATFORMS", []):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Vehicle pairing-holder survives untouched.
    assert vehicle_subentry_id in entry.subentries
    # A fresh, unpaired energy config-holder now exists.
    energy_subentries = entry.get_subentries_of_type(SUBENTRY_TYPE_ENERGY_SITE)
    assert len(energy_subentries) == 1
    assert CONF_HOST not in energy_subentries[0].data
    # Cloud energy on the parent is untouched (no local routing).
    api = entry.runtime_data.energysites[0].api
    assert isinstance(api, EnergySite)
    assert not isinstance(api, EnergySiteRouter)


async def test_direct_upgrade_preserves_pairing_and_reactivates_local(
    hass: HomeAssistant,
) -> None:
    """v6.0.0/6.0.1 -> v6.0.4 direct: old host/password reused, local control returns.

    An Option-1 install parents its energy entities under an energy_site
    subentry carrying ``{site_id, host, password}``. On setup the back-migration
    reparents those entities to the main entry (leaving subentry data intact),
    then merge-on-ensure preserves host/password, so routing re-activates with
    no re-pairing.
    """
    base = mock_config_entry()
    entry = MockConfigEntry(
        domain=base.domain,
        version=base.version,
        minor_version=base.minor_version,
        unique_id=base.unique_id,
        data=dict(base.data),
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
                unique_id=str(POWERWALL_SITE_ID),
                title="Test Energy Site",
                data={
                    CONF_SITE_ID: POWERWALL_SITE_ID,
                    CONF_HOST: HOST,
                    CONF_PASSWORD: PASSWORD,
                },
            )
        ],
    )
    entry.add_to_hass(hass)
    energy_subentry_id = entry.get_subentries_of_type(SUBENTRY_TYPE_ENERGY_SITE)[
        0
    ].subentry_id
    _, energy_entity_id = _seed_subentry_device_and_entity(
        hass,
        entry,
        energy_subentry_id,
        str(POWERWALL_SITE_ID),
        f"{POWERWALL_SITE_ID}_solar_power",
    )

    with (
        patch(
            "homeassistant.components.teslemetry._async_get_rsa_key_pem",
            return_value=_TEST_RSA_KEY_PEM,
        ),
        patch("homeassistant.components.teslemetry.PLATFORMS", []),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # The old local pairing is preserved and merged, not dropped.
    subentry = entry.subentries[energy_subentry_id]
    assert subentry.data[CONF_HOST] == HOST
    assert subentry.data[CONF_PASSWORD] == PASSWORD
    # Local control re-activates automatically (router wraps the cloud API).
    assert isinstance(entry.runtime_data.energysites[0].api, EnergySiteRouter)
    # The old subentry-parented entity is reparented onto the main entry.
    reg_entry = er.async_get(hass).async_get(energy_entity_id)
    assert reg_entry is not None
    assert reg_entry.config_subentry_id is None
