"""Issue registry helpers for the pinned core base (HACS-only, TEMPORARY).

The integration imports this module as ``ir`` in place of
``homeassistant.helpers.issue_registry``. On a core with issue refreshes, every
name is core's own. The pinned core release has no ``async_begin_issues_refresh``
or ``async_keep_issue`` and no ``config_entry_id`` on issues, so this module adds
a local equivalent: an issue belongs to the config entry its ``data["entry_id"]``
names. Retire it once the floor reaches the first core release with
``async_begin_issues_refresh``.
"""

from collections.abc import Iterable
import re
from types import TracebackType
from typing import Any, Self

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util.hass_dict import HassKey

_CORE_HAS_REFRESH = hasattr(ir, "async_begin_issues_refresh")
_REFRESHES: HassKey[list[IssuesRefresh]] = HassKey("teslemetry_hacs_issue_refreshes")


def __getattr__(name: str) -> Any:
    """Return core's issue registry name for everything this module lacks."""
    return getattr(ir, name)


class IssuesRefresh:
    """Refresh of a set of issues, for a core without issue refreshes.

    Issues in the set which have not been created, deleted or kept when the
    refresh finishes are deleted.
    """

    def __init__(self, hass: HomeAssistant, keys: set[tuple[str, str]]) -> None:
        """Initialize the refresh with the issues it decides about."""
        self._hass = hass
        self._untouched = keys
        hass.data.setdefault(_REFRESHES, []).append(self)

    def _touch(self, key: tuple[str, str]) -> None:
        self._untouched.discard(key)

    @callback
    def async_finish(self) -> None:
        """Finish the refresh and delete the issues nothing touched."""
        if not self._async_end():
            return
        issue_registry = ir.async_get(self._hass)
        for domain, issue_id in self._untouched:
            issue_registry.async_delete(domain, issue_id)

    @callback
    def async_cancel(self) -> None:
        """Cancel the refresh without deleting any issue."""
        self._async_end()

    def _async_end(self) -> bool:
        refreshes = self._hass.data.get(_REFRESHES, [])
        if self not in refreshes:
            return False
        refreshes.remove(self)
        return True

    def __enter__(self) -> Self:
        """Enter the refresh."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Finish the refresh on a clean exit, cancel it on an exception."""
        if exc_type is None:
            self.async_finish()
        else:
            self.async_cancel()


def _async_touch(hass: HomeAssistant, domain: str, issue_id: str) -> None:
    for refresh in hass.data.get(_REFRESHES, []):
        refresh._touch((domain, issue_id))  # noqa: SLF001


@callback
def async_begin_issues_refresh(
    hass: HomeAssistant,
    domain: str,
    *,
    issue_id_pattern: str | re.Pattern[str] | None = None,
    issue_ids: Iterable[str] | None = None,
    config_entry_id: str | None = None,
) -> Any:
    """Begin a refresh of a set of issues."""
    if _CORE_HAS_REFRESH:
        return ir.async_begin_issues_refresh(
            hass,
            domain,
            issue_id_pattern=issue_id_pattern,
            issue_ids=issue_ids,
            config_entry_id=config_entry_id,
        )
    pattern = re.compile(issue_id_pattern) if issue_id_pattern is not None else None
    wanted = set(issue_ids) if issue_ids is not None else None
    keys = {
        key
        for key, issue in ir.async_get(hass).issues.items()
        if issue.domain == domain
        and (pattern is None or pattern.match(issue.issue_id))
        and (wanted is None or issue.issue_id in wanted)
        and (
            config_entry_id is None
            or (issue.data or {}).get("entry_id") == config_entry_id
        )
    }
    return IssuesRefresh(hass, keys)


@callback
def async_keep_issue(hass: HomeAssistant, domain: str, issue_id: str) -> None:
    """Keep an issue in all active refreshes without creating or updating it."""
    if _CORE_HAS_REFRESH:
        ir.async_keep_issue(hass, domain, issue_id)
        return
    _async_touch(hass, domain, issue_id)


@callback
def async_create_issue(
    hass: HomeAssistant,
    domain: str,
    issue_id: str,
    *,
    config_entry_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Create an issue, or replace an existing one."""
    if _CORE_HAS_REFRESH:
        ir.async_create_issue(
            hass, domain, issue_id, config_entry_id=config_entry_id, **kwargs
        )
        return
    ir.async_create_issue(hass, domain, issue_id, **kwargs)
    _async_touch(hass, domain, issue_id)


@callback
def async_delete_issue(hass: HomeAssistant, domain: str, issue_id: str) -> None:
    """Delete an issue."""
    ir.async_delete_issue(hass, domain, issue_id)
    if not _CORE_HAS_REFRESH:
        _async_touch(hass, domain, issue_id)
