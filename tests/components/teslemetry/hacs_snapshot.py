"""Registry entry snapshots across serializer forms (HACS-only, TEMPORARY).

Core dev's snapshot serializer writes a registry entry's device_id, via_device_id
and parent_device_id as a reference to the device (core #188133, #188728,
#188724), and its config_subentry_id as a reference to the subentry or None
(core #188744). The pinned core release's serializer writes <ANY> (via_device_id
keeps None), and a composed build mixes snapshots written before and after those
changes. This extension matches each of these values in either form. Retire it
once the pinned core release's serializer has _serializable_subentry_id.
"""

import re

from pytest_homeassistant import syrupy as ha_syrupy
from syrupy.assertion import SnapshotAssertion
from syrupy.types import SerializableData

_REFERENCE = r"<\w+ (?:identifiers|connections|subentry_type)=.*>"
_ANY_ID = re.compile(
    rf"^(\s*'(?:device_id|parent_device_id|config_subentry_id)': )"
    rf"(?:None|{_REFERENCE})(,)$",
    re.MULTILINE,
)
_VIA_DEVICE_ID = re.compile(
    rf"^(\s*'via_device_id': ){_REFERENCE}(,)$",
    re.MULTILINE,
)


def _any_ids(data: SerializableData) -> SerializableData:
    """Write each changed id as the pinned core release's serializer does."""
    if not isinstance(data, str):
        return data
    data = _ANY_ID.sub(r"\1<ANY>\2", data)
    return _VIA_DEVICE_ID.sub(r"\1<ANY>\2", data)


class _Extension(ha_syrupy.HomeAssistantSnapshotExtension):
    """Home Assistant snapshot extension that accepts core dev's id forms."""

    def matches(
        self, *, serialized_data: SerializableData, snapshot_data: SerializableData
    ) -> bool:
        """Compare the data with each changed id written as <ANY>."""
        return _any_ids(serialized_data) == _any_ids(snapshot_data)


def use_any_device_id(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Return the snapshot assertion that accepts core dev's id forms."""
    if hasattr(ha_syrupy.HomeAssistantSnapshotSerializer, "_serializable_subentry_id"):
        return snapshot
    return snapshot.use_extension(_Extension)
