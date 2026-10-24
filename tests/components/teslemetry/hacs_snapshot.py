"""Entity registry entry snapshots across serializer forms (HACS-only, TEMPORARY).

Core dev's snapshot serializer writes an entity registry entry's device_id as a
reference to the device, or None (core #188133). The pinned core release's
serializer writes <ANY>, and a composed build mixes snapshots written before and
after that change. This extension matches a device_id in either form. Retire it
once the pinned core release's serializer has _serializable_device_id.
"""

import re

from pytest_homeassistant import syrupy as ha_syrupy
from syrupy.assertion import SnapshotAssertion
from syrupy.types import SerializableData

_DEVICE_ID = re.compile(
    r"^(\s*'device_id': )(?:None|<\w+ (?:identifiers|connections)=.*>)(,)$",
    re.MULTILINE,
)


def _any_device_id(data: SerializableData) -> SerializableData:
    """Write every device_id as the pinned core release's serializer does."""
    if not isinstance(data, str):
        return data
    return _DEVICE_ID.sub(r"\1<ANY>\2", data)


class _Extension(ha_syrupy.HomeAssistantSnapshotExtension):
    """Home Assistant snapshot extension that accepts core dev's device_id form."""

    def matches(
        self, *, serialized_data: SerializableData, snapshot_data: SerializableData
    ) -> bool:
        """Compare the data with every device_id written as <ANY>."""
        return _any_device_id(serialized_data) == _any_device_id(snapshot_data)


def use_any_device_id(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Return the snapshot assertion that accepts core dev's device_id form."""
    if hasattr(ha_syrupy.HomeAssistantSnapshotSerializer, "_serializable_device_id"):
        return snapshot
    return snapshot.use_extension(_Extension)
