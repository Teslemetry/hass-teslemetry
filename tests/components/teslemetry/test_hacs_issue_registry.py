"""Test the HACS-only issue refresh helpers for the pinned core release."""

import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.teslemetry import hacs_issue_registry
from homeassistant.components.teslemetry.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir


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


def test_old_refresh_name_is_kept() -> None:
    """The old name of the refresh helper begins the same refresh."""
    assert (
        hacs_issue_registry.async_begin_issues_refresh
        is hacs_issue_registry.async_refresh_issues
    )


async def test_refresh_deletes_stale_issues_of_its_entry(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """A refresh deletes the stale issues of its config entry.

    Issues created again during the refresh, issues of another config entry and
    issues outside the refresh's set are left alone.
    """
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    other_entry = MockConfigEntry(domain=DOMAIN)
    other_entry.add_to_hass(hass)
    for issue_id in ("gateway_not_found_111", "gateway_not_found_222", "key_GONE"):
        _create_issue(hass, issue_id, entry.entry_id)
    _create_issue(hass, "gateway_not_found_333", other_entry.entry_id)

    with hacs_issue_registry.async_refresh_issues(
        hass,
        DOMAIN,
        issue_id_pattern="gateway_not_found_",
        config_entry_id=entry.entry_id,
    ):
        _create_issue(hass, "gateway_not_found_222", entry.entry_id)

    assert issue_registry.async_get_issue(DOMAIN, "gateway_not_found_111") is None
    assert issue_registry.async_get_issue(DOMAIN, "gateway_not_found_222")
    assert issue_registry.async_get_issue(DOMAIN, "key_GONE")
    assert issue_registry.async_get_issue(DOMAIN, "gateway_not_found_333")


async def test_refresh_deleted_issue_stays_deleted(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """An issue deleted during a refresh is not created again by it."""
    _create_issue(hass, "gateway_not_found_1", "entry")

    with hacs_issue_registry.async_refresh_issues(
        hass, DOMAIN, issue_ids=["gateway_not_found_1"]
    ):
        hacs_issue_registry.async_delete_issue(hass, DOMAIN, "gateway_not_found_1")

    assert issue_registry.async_get_issue(DOMAIN, "gateway_not_found_1") is None


async def test_cancelled_refresh_deletes_nothing(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """A cancelled refresh, as a failed setup leaves it, deletes nothing."""
    _create_issue(hass, "gateway_not_found_1", "entry")

    refresh = hacs_issue_registry.async_refresh_issues(
        hass, DOMAIN, issue_id_pattern="gateway_not_found_"
    )
    refresh.async_cancel()
    refresh.async_finish()

    assert issue_registry.async_get_issue(DOMAIN, "gateway_not_found_1")


async def test_refresh_keeps_touched_issues(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """A refresh deletes only the issues in its set that nothing touched."""
    for issue_id in ("gateway_not_found_1", "gateway_not_found_2", "other_3"):
        _create_issue(hass, issue_id, "entry")
    ir.async_ignore_issue(hass, DOMAIN, "gateway_not_found_1", True)

    with hacs_issue_registry.async_refresh_issues(
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
        hacs_issue_registry.async_refresh_issues(
            hass, DOMAIN, issue_ids=["gateway_not_found_1"]
        ),
    ):
        raise RuntimeError

    assert issue_registry.async_get_issue(DOMAIN, "gateway_not_found_1")
