"""Test the HACS-only v6.0.0/6.0.1 -> v6.0.2 subentry back-migration."""

from homeassistant.components.teslemetry import hacs_migrate_subentry_entities
from homeassistant.components.teslemetry.const import (
    CONF_VIN,
    DOMAIN,
    SUBENTRY_TYPE_VEHICLE,
)
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from . import mock_config_entry

from tests.common import MockConfigEntry

VIN = "LRW3F7EK4NC700000"
SITE_ID = "123456789"

# The v6.0.0/6.0.1 betas shipped an "energy_site" subentry type that v6.0.2 no
# longer defines; a real upgrade still carries it, so the test uses the literal.
SUBENTRY_TYPE_ENERGY_SITE = "energy_site"


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
