"""Test the HACS-only issue refresh helpers for the pinned core release."""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry
from tesla_fleet_api.exceptions import TeslaFleetError

from homeassistant.components.teslemetry import hacs_issue_registry
from homeassistant.components.teslemetry.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from . import mock_config_entry


def _create_issue(hass: HomeAssistant, issue_id: str, entry_id: str) -> None:
    """Create a repair issue owned by the given config entry."""
    hacs_issue_registry.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        config_entry_id=entry_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="gateway_not_found",
        translation_placeholders={"site": "Energy Site"},
        data={"entry_id": entry_id},
    )


def test_core_names_pass_through() -> None:
    """Names the module does not define are core's own."""
    assert hacs_issue_registry.IssueSeverity is ir.IssueSeverity
    assert hacs_issue_registry.async_get is ir.async_get


async def test_stale_repairs_deleted_on_setup(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """Vehicle and gateway repairs of the entry which are stale are deleted.

    Repairs owned by another config entry are left alone.
    """
    entry = mock_config_entry()
    entry.add_to_hass(hass)
    other_entry = MockConfigEntry(domain=DOMAIN)
    other_entry.add_to_hass(hass)
    stale_issue_ids = ["key_GONE", "gateway_not_found_111"]
    kept_issue_ids = ["key_OTHER_ACCOUNT", "gateway_not_found_222"]
    for issue_id in stale_issue_ids:
        _create_issue(hass, issue_id, entry.entry_id)
    for issue_id in kept_issue_ids:
        _create_issue(hass, issue_id, other_entry.entry_id)

    with patch("homeassistant.components.teslemetry.PLATFORMS", []):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    for issue_id in stale_issue_ids:
        assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
    for issue_id in kept_issue_ids:
        assert issue_registry.async_get_issue(DOMAIN, issue_id)


async def test_gateway_repairs_kept_on_setup_failure(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry, mock_live_status: AsyncMock
) -> None:
    """A failed setup leaves the gateway repairs alone."""
    entry = mock_config_entry()
    entry.add_to_hass(hass)
    _create_issue(hass, "gateway_not_found_111", entry.entry_id)
    mock_live_status.side_effect = TeslaFleetError

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert issue_registry.async_get_issue(DOMAIN, "gateway_not_found_111")


async def test_refresh_keeps_touched_issues(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """A refresh deletes only the issues in its set that nothing touched."""
    for issue_id in ("gateway_not_found_1", "gateway_not_found_2", "other_3"):
        _create_issue(hass, issue_id, "entry")
    ir.async_ignore_issue(hass, DOMAIN, "gateway_not_found_1", True)

    with hacs_issue_registry.async_begin_issues_refresh(
        hass, DOMAIN, issue_id_pattern="gateway_not_found_", config_entry_id="entry"
    ):
        hacs_issue_registry.async_keep_issue(hass, DOMAIN, "gateway_not_found_1")

    issue = issue_registry.async_get_issue(DOMAIN, "gateway_not_found_1")
    assert issue is not None
    assert issue.dismissed_version is not None
    assert issue_registry.async_get_issue(DOMAIN, "gateway_not_found_2") is None
    assert issue_registry.async_get_issue(DOMAIN, "other_3")


async def test_refresh_cancelled_on_exception(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """A refresh left by an exception deletes nothing."""
    _create_issue(hass, "gateway_not_found_1", "entry")

    with (
        pytest.raises(RuntimeError),
        hacs_issue_registry.async_begin_issues_refresh(
            hass, DOMAIN, issue_ids=["gateway_not_found_1"]
        ),
    ):
        raise RuntimeError

    assert issue_registry.async_get_issue(DOMAIN, "gateway_not_found_1")
