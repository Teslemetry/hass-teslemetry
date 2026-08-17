"""Test the HACS-only config-subentry back-migration.

Every shipped install shape that ever parented entities/devices under a config
subentry must upgrade directly onto the current main-entry model without losing
registry identity (UUID, entity_id, unique_id, device_id) or holder credentials.
The migration runs before inventory, so a temporarily inaccessible or no-longer
emitted record is normalized just like an active one.
"""

import pytest

from homeassistant.components.teslemetry import (
    hacs_migrate_subentry_entities,
    hacs_remove_empty_holder_subentries,
)
from homeassistant.components.teslemetry.const import DOMAIN
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from . import mock_config_entry

from tests.common import MockConfigEntry

# Real upgrades still carry the subentry types the entity-parenting layout
# created; current main no longer defines them, so the tests use the literals.
SUBENTRY_TYPE_VEHICLE = "vehicle"
SUBENTRY_TYPE_ENERGY_SITE = "energy_site"

VIN = "LRW3F7EK4NC700001"
VIN_INACCESSIBLE = "LRW3F7EK4NC700002"
VIN_RECORD_OWNER = "LRW3F7EK4NC700003"
SITE_BATTERY = "111111111"
SITE_SOLAR = "222222222"
SITE_BATTERY_UNPAIRED = "333333333"

# Local-control credentials the v6.0.0/6.0.1 and later holders carry; the
# migration reparents registry records only and must never disturb these.
VEHICLE_HOLDER_DATA = {"vin": VIN, "address": "AA:BB:CC:DD:EE:FF"}
BATTERY_HOLDER_DATA = {
    "site_id": SITE_BATTERY,
    "host": "192.168.1.50",
    "password": "s3cret",
    "key": "keymaterial",
}
SOLAR_HOLDER_DATA = {"site_id": SITE_SOLAR}

# Auto-created (unpaired) holders older builds left for every product; their
# data is just the identity key, so the forward cleanup may remove them.
EMPTY_VEHICLE_HOLDER_DATA = {"vin": VIN}
EMPTY_BATTERY_HOLDER_DATA = {"site_id": SITE_BATTERY}


def _device_on_main_entry(device: dr.DeviceEntry, entry: MockConfigEntry) -> bool:
    """Return whether a device is owned by the main entry (no subentry).

    Handles both the stable multi-owner registry and the dev single-owner one.
    """
    if hasattr(device, "config_subentry_id"):
        return device.config_subentry_id is None
    return device.config_entries_subentries.get(entry.entry_id) == {None}


def _seed_device(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    *,
    identifier: str,
    subentry_id: str | None,
) -> dr.DeviceEntry:
    """Create a device owned by the given subentry (or the main entry)."""
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id=subentry_id,
        identifiers={(DOMAIN, identifier)},
    )


def _seed_entity(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    *,
    unique_id: str,
    subentry_id: str | None,
    device_id: str | None = None,
    disabled: bool = False,
) -> er.RegistryEntry:
    """Create an entity owned by the given subentry (or the main entry)."""
    return er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        unique_id,
        config_entry=entry,
        config_subentry_id=subentry_id,
        device_id=device_id,
        disabled_by=er.RegistryEntryDisabler.USER if disabled else None,
    )


def _entity_parenting_entry() -> MockConfigEntry:
    """Return an entry shaped like an entity-parenting install with holders."""
    entry = mock_config_entry()
    return MockConfigEntry(
        domain=entry.domain,
        version=entry.version,
        unique_id=entry.unique_id,
        data=dict(entry.data),
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_VEHICLE,
                unique_id=VIN,
                title="Test Vehicle",
                data=VEHICLE_HOLDER_DATA,
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_VEHICLE,
                unique_id=VIN_INACCESSIBLE,
                title="Inaccessible Vehicle",
                data={"vin": VIN_INACCESSIBLE},
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
                unique_id=SITE_BATTERY,
                title="Battery Site",
                data=BATTERY_HOLDER_DATA,
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
                unique_id=SITE_SOLAR,
                title="Solar Site",
                data=SOLAR_HOLDER_DATA,
            ),
        ],
    )


def _entry_with_subentries(*subentries_data: ConfigSubentryData) -> MockConfigEntry:
    """Return a Teslemetry entry carrying the given holder subentries."""
    entry = mock_config_entry()
    return MockConfigEntry(
        domain=entry.domain,
        version=entry.version,
        unique_id=entry.unique_id,
        data=dict(entry.data),
        subentries_data=list(subentries_data),
    )


def _subentry_id(entry: MockConfigEntry, unique_id: str) -> str:
    """Return the id of the subentry with the given unique id."""
    for subentry_id, subentry in entry.subentries.items():
        if subentry.unique_id == unique_id:
            return subentry_id
    raise AssertionError(f"no subentry with unique_id {unique_id}")


async def test_entity_parenting_install_reparents_everything(
    hass: HomeAssistant,
) -> None:
    """Every record under a subentry moves to the main entry, identity intact.

    Covers the v5.2/v5.3 and v6.0.0/v6.0.1 entity-parenting shapes across an
    active vehicle, a battery site, a solar-only site, a temporarily
    inaccessible vehicle, a disabled entity, and a no-longer-emitted entity.
    """
    entry = _entity_parenting_entry()
    entry.add_to_hass(hass)

    vehicle_sub = _subentry_id(entry, VIN)
    inaccessible_sub = _subentry_id(entry, VIN_INACCESSIBLE)
    battery_sub = _subentry_id(entry, SITE_BATTERY)
    solar_sub = _subentry_id(entry, SITE_SOLAR)

    # Active vehicle: a device with a live entity, a disabled entity, and an
    # entity whose field is no longer emitted.
    vehicle_device = _seed_device(hass, entry, identifier=VIN, subentry_id=vehicle_sub)
    vehicle_entity = _seed_entity(
        hass,
        entry,
        unique_id=f"{VIN}_battery_level",
        subentry_id=vehicle_sub,
        device_id=vehicle_device.id,
    )
    disabled_entity = _seed_entity(
        hass,
        entry,
        unique_id=f"{VIN}_charging",
        subentry_id=vehicle_sub,
        device_id=vehicle_device.id,
        disabled=True,
    )
    removed_entity = _seed_entity(
        hass,
        entry,
        unique_id=f"{VIN}_legacy_removed_field",
        subentry_id=vehicle_sub,
        device_id=vehicle_device.id,
    )

    # A vehicle that is out of scope / asleep on this boot.
    inaccessible_device = _seed_device(
        hass, entry, identifier=VIN_INACCESSIBLE, subentry_id=inaccessible_sub
    )
    inaccessible_entity = _seed_entity(
        hass,
        entry,
        unique_id=f"{VIN_INACCESSIBLE}_battery_level",
        subentry_id=inaccessible_sub,
        device_id=inaccessible_device.id,
    )

    # Battery and solar-only energy sites.
    battery_device = _seed_device(
        hass, entry, identifier=SITE_BATTERY, subentry_id=battery_sub
    )
    battery_entity = _seed_entity(
        hass,
        entry,
        unique_id=f"{SITE_BATTERY}_battery_power",
        subentry_id=battery_sub,
        device_id=battery_device.id,
    )
    solar_device = _seed_device(
        hass, entry, identifier=SITE_SOLAR, subentry_id=solar_sub
    )
    solar_entity = _seed_entity(
        hass,
        entry,
        unique_id=f"{SITE_SOLAR}_solar_power",
        subentry_id=solar_sub,
        device_id=solar_device.id,
    )

    entities = (
        vehicle_entity,
        disabled_entity,
        removed_entity,
        inaccessible_entity,
        battery_entity,
        solar_entity,
    )
    devices = (
        vehicle_device,
        inaccessible_device,
        battery_device,
        solar_device,
    )
    # Snapshot exact identity before the migration.
    before = {e.entity_id: (e.id, e.unique_id, e.device_id) for e in entities}
    device_ids = {d.id for d in devices}

    hacs_migrate_subentry_entities(hass, entry)

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    for entity_id, (reg_id, unique_id, device_id) in before.items():
        after = entity_registry.async_get(entity_id)
        assert after is not None, f"{entity_id} was deleted"
        assert after.id == reg_id
        assert after.entity_id == entity_id
        assert after.unique_id == unique_id
        assert after.device_id == device_id
        assert after.config_subentry_id is None
        assert after.config_entry_id == entry.entry_id

    # The disabled entity is reparented but stays disabled.
    assert (
        entity_registry.async_get(disabled_entity.entity_id).disabled_by
        is er.RegistryEntryDisabler.USER
    )

    for device_id in device_ids:
        after = device_registry.async_get(device_id)
        assert after is not None, "a device was deleted"
        assert after.id == device_id
        assert _device_on_main_entry(after, entry)

    # Holder subentries and their local-control credentials are untouched.
    assert entry.subentries[vehicle_sub].data == VEHICLE_HOLDER_DATA
    assert entry.subentries[battery_sub].data == BATTERY_HOLDER_DATA
    assert entry.subentries[solar_sub].data == SOLAR_HOLDER_DATA
    assert set(entry.subentries) == {
        vehicle_sub,
        inaccessible_sub,
        battery_sub,
        solar_sub,
    }


async def test_already_parented_install_is_ownership_noop(hass: HomeAssistant) -> None:
    """v6.0.2-v6.0.8 records already on the main entry are left untouched.

    Holders are present (vehicle only, then vehicle + energy) and their
    credentials must survive; the migration touches ownership on nothing.
    """
    entry = mock_config_entry()
    entry_obj = MockConfigEntry(
        domain=entry.domain,
        version=entry.version,
        unique_id=entry.unique_id,
        data=dict(entry.data),
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_VEHICLE,
                unique_id=VIN,
                title="Test Vehicle",
                data=VEHICLE_HOLDER_DATA,
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
                unique_id=SITE_BATTERY,
                title="Battery Site",
                data=BATTERY_HOLDER_DATA,
            ),
        ],
    )
    entry_obj.add_to_hass(hass)
    vehicle_sub = _subentry_id(entry_obj, VIN)
    battery_sub = _subentry_id(entry_obj, SITE_BATTERY)

    device = _seed_device(hass, entry_obj, identifier=VIN, subentry_id=None)
    entity = _seed_entity(
        hass,
        entry_obj,
        unique_id=f"{VIN}_battery_level",
        subentry_id=None,
        device_id=device.id,
    )

    hacs_migrate_subentry_entities(hass, entry_obj)

    after_entity = er.async_get(hass).async_get(entity.entity_id)
    assert after_entity.id == entity.id
    assert after_entity.unique_id == entity.unique_id
    assert after_entity.config_subentry_id is None
    after_device = dr.async_get(hass).async_get(device.id)
    assert _device_on_main_entry(after_device, entry_obj)

    assert entry_obj.subentries[vehicle_sub].data == VEHICLE_HOLDER_DATA
    assert entry_obj.subentries[battery_sub].data == BATTERY_HOLDER_DATA


async def test_mixed_install_reparents_stale_device(hass: HomeAssistant) -> None:
    """v6.0.9/v6.0.10 mixed state: parented entities plus a stale legacy device.

    A device left under a legacy subentry is normalized while the already
    parented records are untouched.
    """
    entry = mock_config_entry()
    entry_obj = MockConfigEntry(
        domain=entry.domain,
        version=entry.version,
        unique_id=entry.unique_id,
        data=dict(entry.data),
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_VEHICLE,
                unique_id=VIN,
                title="Test Vehicle",
                data=VEHICLE_HOLDER_DATA,
            ),
        ],
    )
    entry_obj.add_to_hass(hass)
    vehicle_sub = _subentry_id(entry_obj, VIN)

    parented_device = _seed_device(hass, entry_obj, identifier=VIN, subentry_id=None)
    parented_entity = _seed_entity(
        hass,
        entry_obj,
        unique_id=f"{VIN}_battery_level",
        subentry_id=None,
        device_id=parented_device.id,
    )
    stale_device = _seed_device(
        hass, entry_obj, identifier="stale-device", subentry_id=vehicle_sub
    )

    hacs_migrate_subentry_entities(hass, entry_obj)

    after_parented = dr.async_get(hass).async_get(parented_device.id)
    assert _device_on_main_entry(after_parented, entry_obj)
    after_stale = dr.async_get(hass).async_get(stale_device.id)
    assert after_stale is not None
    assert after_stale.id == stale_device.id
    assert _device_on_main_entry(after_stale, entry_obj)
    assert er.async_get(hass).async_get(parented_entity.entity_id) is not None
    assert entry_obj.subentries[vehicle_sub].data == VEHICLE_HOLDER_DATA


async def test_migration_is_idempotent(hass: HomeAssistant) -> None:
    """A second run over already-normalized state changes nothing."""
    entry = _entity_parenting_entry()
    entry.add_to_hass(hass)
    vehicle_sub = _subentry_id(entry, VIN)

    device = _seed_device(hass, entry, identifier=VIN, subentry_id=vehicle_sub)
    entity = _seed_entity(
        hass,
        entry,
        unique_id=f"{VIN}_battery_level",
        subentry_id=vehicle_sub,
        device_id=device.id,
    )

    hacs_migrate_subentry_entities(hass, entry)
    first_entity = er.async_get(hass).async_get(entity.entity_id)
    first_device = dr.async_get(hass).async_get(device.id)

    hacs_migrate_subentry_entities(hass, entry)
    second_entity = er.async_get(hass).async_get(entity.entity_id)
    second_device = dr.async_get(hass).async_get(device.id)

    assert first_entity == second_entity
    assert first_device == second_device
    assert second_entity.config_subentry_id is None
    assert _device_on_main_entry(second_device, entry)


async def test_no_subentries_is_noop(hass: HomeAssistant) -> None:
    """A fresh install with no subentries is left untouched."""
    entry = mock_config_entry()
    entry.add_to_hass(hass)
    entity = _seed_entity(
        hass, entry, unique_id=f"{VIN}_battery_level", subentry_id=None
    )

    hacs_migrate_subentry_entities(hass, entry)

    after = er.async_get(hass).async_get(entity.entity_id)
    assert after is not None
    assert after.id == entity.id
    assert after.config_subentry_id is None


@pytest.mark.parametrize("run_twice", [False, True])
async def test_recorder_identity_preserved_for_sensor(
    hass: HomeAssistant, run_twice: bool
) -> None:
    """A sensor keeps its exact entity_id and unique ID so history stays attached.

    Recorder rows key off the entity_id; a preserved entity_id (never a
    delete-and-recreate) is what keeps existing history and statistics attached.
    """
    entry = _entity_parenting_entry()
    entry.add_to_hass(hass)
    vehicle_sub = _subentry_id(entry, VIN)
    device = _seed_device(hass, entry, identifier=VIN, subentry_id=vehicle_sub)
    entity = _seed_entity(
        hass,
        entry,
        unique_id=f"{VIN}_battery_level",
        subentry_id=vehicle_sub,
        device_id=device.id,
    )
    original_entity_id = entity.entity_id
    original_reg_id = entity.id

    hacs_migrate_subentry_entities(hass, entry)
    if run_twice:
        hacs_migrate_subentry_entities(hass, entry)

    after = er.async_get(hass).async_get(original_entity_id)
    assert after is not None
    assert after.id == original_reg_id
    assert after.entity_id == original_entity_id
    assert after.unique_id == f"{VIN}_battery_level"


async def test_empty_vehicle_holder_removed(hass: HomeAssistant) -> None:
    """An unpaired vehicle holder (identity key only) is removed."""
    entry = _entry_with_subentries(
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_VEHICLE,
            unique_id=VIN,
            title="Test Vehicle",
            data=EMPTY_VEHICLE_HOLDER_DATA,
        ),
    )
    entry.add_to_hass(hass)

    hacs_remove_empty_holder_subentries(hass, entry)

    assert entry.subentries == {}


async def test_empty_energy_holder_removed(hass: HomeAssistant) -> None:
    """An unpaired energy holder (identity key only) is removed."""
    entry = _entry_with_subentries(
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
            unique_id=SITE_BATTERY,
            title="Battery Site",
            data=EMPTY_BATTERY_HOLDER_DATA,
        ),
    )
    entry.add_to_hass(hass)

    hacs_remove_empty_holder_subentries(hass, entry)

    assert entry.subentries == {}


async def test_vehicle_holder_with_address_kept(hass: HomeAssistant) -> None:
    """A vehicle holder carrying a Bluetooth address is kept with its data."""
    entry = _entry_with_subentries(
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_VEHICLE,
            unique_id=VIN,
            title="Test Vehicle",
            data=VEHICLE_HOLDER_DATA,
        ),
    )
    entry.add_to_hass(hass)
    vehicle_sub = _subentry_id(entry, VIN)

    hacs_remove_empty_holder_subentries(hass, entry)

    assert set(entry.subentries) == {vehicle_sub}
    assert entry.subentries[vehicle_sub].data == VEHICLE_HOLDER_DATA


async def test_energy_holder_with_credentials_kept(hass: HomeAssistant) -> None:
    """An energy holder carrying Powerwall credentials is kept with its data."""
    entry = _entry_with_subentries(
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
            unique_id=SITE_BATTERY,
            title="Battery Site",
            data=BATTERY_HOLDER_DATA,
        ),
    )
    entry.add_to_hass(hass)
    battery_sub = _subentry_id(entry, SITE_BATTERY)

    hacs_remove_empty_holder_subentries(hass, entry)

    assert set(entry.subentries) == {battery_sub}
    assert entry.subentries[battery_sub].data == BATTERY_HOLDER_DATA


async def test_holder_owning_registry_record_is_kept(hass: HomeAssistant) -> None:
    """An empty holder that still owns a device or entity is left alone.

    Normalization should have reparented every record first, but the cleanup
    asserts emptiness rather than assuming it.
    """
    entry = _entry_with_subentries(
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_VEHICLE,
            unique_id=VIN,
            title="Test Vehicle",
            data=EMPTY_VEHICLE_HOLDER_DATA,
        ),
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
            unique_id=SITE_BATTERY,
            title="Battery Site",
            data=EMPTY_BATTERY_HOLDER_DATA,
        ),
    )
    entry.add_to_hass(hass)
    vehicle_sub = _subentry_id(entry, VIN)
    battery_sub = _subentry_id(entry, SITE_BATTERY)

    # The vehicle holder still owns a device; the energy holder still owns an
    # entity. Neither may be removed.
    _seed_device(hass, entry, identifier=VIN, subentry_id=vehicle_sub)
    _seed_entity(
        hass,
        entry,
        unique_id=f"{SITE_BATTERY}_battery_power",
        subentry_id=battery_sub,
    )

    hacs_remove_empty_holder_subentries(hass, entry)

    assert set(entry.subentries) == {vehicle_sub, battery_sub}


async def test_cleanup_is_idempotent(hass: HomeAssistant) -> None:
    """A second run leaves the survivors and their data untouched."""
    entry = _entry_with_subentries(
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_VEHICLE,
            unique_id=VIN,
            title="Test Vehicle",
            data=EMPTY_VEHICLE_HOLDER_DATA,
        ),
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
            unique_id=SITE_BATTERY,
            title="Battery Site",
            data=BATTERY_HOLDER_DATA,
        ),
    )
    entry.add_to_hass(hass)
    battery_sub = _subentry_id(entry, SITE_BATTERY)

    hacs_remove_empty_holder_subentries(hass, entry)
    after_first = dict(entry.subentries)

    hacs_remove_empty_holder_subentries(hass, entry)

    assert dict(entry.subentries) == after_first
    assert set(entry.subentries) == {battery_sub}
    assert entry.subentries[battery_sub].data == BATTERY_HOLDER_DATA


async def test_no_subentries_cleanup_is_noop(hass: HomeAssistant) -> None:
    """A fresh install with no holders is left untouched."""
    entry = mock_config_entry()
    entry.add_to_hass(hass)

    hacs_remove_empty_holder_subentries(hass, entry)

    assert entry.subentries == {}


async def test_normalize_then_cleanup_in_one_setup(hass: HomeAssistant) -> None:
    """Normalization then cleanup, in order, over a single entity-parenting entry.

    An empty auto-created holder that owned records is removed only after those
    records are reparented; a configured holder that owned records is reparented
    and kept with its credentials.
    """
    entry = _entry_with_subentries(
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_VEHICLE,
            unique_id=VIN,
            title="Paired Vehicle",
            data=VEHICLE_HOLDER_DATA,
        ),
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_VEHICLE,
            unique_id=VIN_INACCESSIBLE,
            title="Unpaired Vehicle",
            data={"vin": VIN_INACCESSIBLE},
        ),
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
            unique_id=SITE_BATTERY,
            title="Battery Site",
            data=BATTERY_HOLDER_DATA,
        ),
    )
    entry.add_to_hass(hass)
    paired_sub = _subentry_id(entry, VIN)
    unpaired_sub = _subentry_id(entry, VIN_INACCESSIBLE)
    battery_sub = _subentry_id(entry, SITE_BATTERY)

    # Both vehicle holders own records under the entity-parenting layout.
    paired_device = _seed_device(hass, entry, identifier=VIN, subentry_id=paired_sub)
    paired_entity = _seed_entity(
        hass,
        entry,
        unique_id=f"{VIN}_battery_level",
        subentry_id=paired_sub,
        device_id=paired_device.id,
    )
    unpaired_device = _seed_device(
        hass, entry, identifier=VIN_INACCESSIBLE, subentry_id=unpaired_sub
    )
    unpaired_entity = _seed_entity(
        hass,
        entry,
        unique_id=f"{VIN_INACCESSIBLE}_battery_level",
        subentry_id=unpaired_sub,
        device_id=unpaired_device.id,
    )

    before = {
        e.entity_id: (e.id, e.unique_id) for e in (paired_entity, unpaired_entity)
    }

    hacs_migrate_subentry_entities(hass, entry)
    hacs_remove_empty_holder_subentries(hass, entry)

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    # Every reparented record survives with its identity intact on the main entry.
    for entity_id, (reg_id, unique_id) in before.items():
        after = entity_registry.async_get(entity_id)
        assert after is not None, f"{entity_id} was deleted"
        assert after.id == reg_id
        assert after.unique_id == unique_id
        assert after.config_subentry_id is None
    for device in (paired_device, unpaired_device):
        after_device = device_registry.async_get(device.id)
        assert after_device is not None
        assert _device_on_main_entry(after_device, entry)

    # The unpaired holder is gone; the configured holders keep their credentials.
    assert set(entry.subentries) == {paired_sub, battery_sub}
    assert entry.subentries[paired_sub].data == VEHICLE_HOLDER_DATA
    assert entry.subentries[battery_sub].data == BATTERY_HOLDER_DATA


async def test_v6_0_8_auto_created_holders_removed_on_upgrade(
    hass: HomeAssistant,
) -> None:
    """A v6.0.8/9/10 install auto-created an identity-only holder per product.

    Under the opt-in model those unpaired holders are legacy leftovers and must
    be removed on upgrade, while a holder later paired (carrying credentials) and
    any holder still owning a registry record are kept. Stable across a second
    setup so the cleanup never churns a live install.
    """
    entry = _entry_with_subentries(
        # Paired over Bluetooth -> keep (carries an address).
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_VEHICLE,
            unique_id=VIN,
            title="Paired Vehicle",
            data=VEHICLE_HOLDER_DATA,
        ),
        # Auto-created, never paired -> remove (identity key only).
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_VEHICLE,
            unique_id=VIN_INACCESSIBLE,
            title="Unpaired Vehicle",
            data={"vin": VIN_INACCESSIBLE},
        ),
        # Auto-created and empty, but still owns a device -> keep (guard).
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_VEHICLE,
            unique_id=VIN_RECORD_OWNER,
            title="Record-owning Vehicle",
            data={"vin": VIN_RECORD_OWNER},
        ),
        # Paired Powerwall -> keep (carries host/password/key).
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
            unique_id=SITE_BATTERY,
            title="Paired Battery",
            data=BATTERY_HOLDER_DATA,
        ),
        # Auto-created battery holder, never paired -> remove.
        ConfigSubentryData(
            subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
            unique_id=SITE_BATTERY_UNPAIRED,
            title="Unpaired Battery",
            data={"site_id": SITE_BATTERY_UNPAIRED},
        ),
    )
    entry.add_to_hass(hass)
    paired_vehicle = _subentry_id(entry, VIN)
    record_owner = _subentry_id(entry, VIN_RECORD_OWNER)
    paired_battery = _subentry_id(entry, SITE_BATTERY)

    # The record-owning holder still owns a device the migration has not yet
    # reparented; the cleanup asserts emptiness rather than assuming it.
    _seed_device(hass, entry, identifier=VIN_RECORD_OWNER, subentry_id=record_owner)

    kept = {paired_vehicle, record_owner, paired_battery}

    hacs_remove_empty_holder_subentries(hass, entry)

    # Both never-paired auto-created holders are gone; everything else survives.
    assert set(entry.subentries) == kept
    assert entry.subentries[paired_vehicle].data == VEHICLE_HOLDER_DATA
    assert entry.subentries[paired_battery].data == BATTERY_HOLDER_DATA

    # A second setup removes nothing further and disturbs no survivor's data.
    hacs_remove_empty_holder_subentries(hass, entry)
    assert set(entry.subentries) == kept
    assert entry.subentries[paired_vehicle].data == VEHICLE_HOLDER_DATA
    assert entry.subentries[paired_battery].data == BATTERY_HOLDER_DATA
