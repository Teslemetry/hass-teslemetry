"""Teslemetry helper functions."""

import asyncio
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any

from tesla_fleet_api.exceptions import InsufficientCredits, TeslaFleetError
from tesla_fleet_api.tesla.bluetooth import TeslaBluetooth

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir

from .const import (
    BLE_PARENT_KEY,
    BLE_PARENT_LOCK_KEY,
    CREDITS_URL,
    DOMAIN,
    LOGGER,
    VEHICLE_KEY_FILE,
)

if TYPE_CHECKING:
    from . import TeslemetryConfigEntry

INSUFFICIENT_CREDITS_ISSUE = "insufficient_credits"

# A credits event clears the insufficient credits issue when the account has
# quota credits still available, or a balance topup has been applied.
CREDITS_QUOTA_FRACTION_THRESHOLD = 0.95
CREDITS_BALANCE_THRESHOLD = 25


def insufficient_credits_issue_id(entry: TeslemetryConfigEntry) -> str:
    """Return the per-config-entry insufficient credits issue id.

    The issue is scoped to the config entry so that one account running out of
    credits does not clear (or get cleared by) another account's repair.
    """
    return f"{INSUFFICIENT_CREDITS_ISSUE}_{entry.entry_id}"


LOCAL_CONTROL_UNAVAILABLE_ISSUE = "local_control_unavailable"


def local_control_issue_id(entry: TeslemetryConfigEntry, site_id: int) -> str:
    """Return the per-site local-control-unavailable issue id.

    Scoped to the config entry and the energy site so one paired site failing to
    reach its local gateway raises (and clears) a repair independent of any other
    site or account.
    """
    return f"{LOCAL_CONTROL_UNAVAILABLE_ISSUE}_{entry.entry_id}_{site_id}"


async def async_get_ble_parent(hass: HomeAssistant) -> TeslaBluetooth:
    """Return a shared TeslaBluetooth parent with the private key loaded."""
    parent: TeslaBluetooth | None = hass.data.get(BLE_PARENT_KEY)
    if parent is not None:
        return parent
    lock: asyncio.Lock = hass.data.setdefault(BLE_PARENT_LOCK_KEY, asyncio.Lock())
    async with lock:
        parent = hass.data.get(BLE_PARENT_KEY)
        if parent is None:
            parent = TeslaBluetooth()  # type: ignore[no-untyped-call]
            await parent.get_private_key(hass.config.path(VEHICLE_KEY_FILE))
            hass.data[BLE_PARENT_KEY] = parent
    return parent


def flatten(
    data: dict[str, Any],
    parent: str | None = None,
    *,
    skip_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Flatten the data structure."""
    result = {}
    for key, value in data.items():
        skip = skip_keys and key in skip_keys
        if parent:
            key = f"{parent}_{key}"
        if isinstance(value, dict) and not skip:
            result.update(flatten(value, key, skip_keys=skip_keys))
        else:
            result[key] = value
    return result


async def handle_command(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    command: Awaitable[dict[str, Any]],
) -> dict[str, Any]:
    """Handle a command."""
    issue_id = insufficient_credits_issue_id(entry)
    try:
        result = await command
    except InsufficientCredits as e:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=INSUFFICIENT_CREDITS_ISSUE,
            translation_placeholders={"credits_url": CREDITS_URL},
            learn_more_url=CREDITS_URL,
        )
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=INSUFFICIENT_CREDITS_ISSUE,
        ) from e
    except TeslaFleetError as e:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_exception",
            translation_placeholders={"message": e.message},
        ) from e
    # The repair is cleared by the credits stream (async_handle_credits), not
    # here: handle_command also wraps energy-site commands, which do not consume
    # command credits, so a successful command is not proof credits are back.
    LOGGER.debug("Command result: %s", result)
    return result


async def handle_vehicle_command(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    command: Awaitable[dict[str, Any]],
) -> Any:
    """Handle a vehicle command."""
    result = await handle_command(hass, entry, command)
    if (response := result.get("response")) is None:
        if error := result.get("error"):
            # No response with error
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_error",
                translation_placeholders={"error": error},
            )
        # No response without error (unexpected)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="command_no_response"
        )
    if (result := response.get("result")) is not True:
        if reason := response.get("reason"):
            if reason in ("already_set", "not_charging", "requested"):
                # Reason is acceptable
                return result
            # Result of false with reason
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_reason",
                translation_placeholders={"reason": reason},
            )
        # Result of false without reason (unexpected)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="command_no_result"
        )
    # Response with result of true
    return result


@callback
def async_handle_credits(
    hass: HomeAssistant, entry: TeslemetryConfigEntry, credits: dict[str, Any]
) -> None:
    """Clear the insufficient credits issue when credits become available."""
    quota = credits.get("quota")
    fraction = quota.get("fraction") if isinstance(quota, dict) else None
    quota_available = (
        isinstance(fraction, (int, float))
        and not isinstance(fraction, bool)
        and fraction < CREDITS_QUOTA_FRACTION_THRESHOLD
    )
    balance = credits.get("balance")
    balance_available = (
        isinstance(balance, (int, float))
        and not isinstance(balance, bool)
        and balance > CREDITS_BALANCE_THRESHOLD
    )
    if quota_available or balance_available:
        ir.async_delete_issue(hass, DOMAIN, insufficient_credits_issue_id(entry))


@callback
def async_update_device_sw_version(
    hass: HomeAssistant, identifier: str, config_entry_id: str, sw_version: str
) -> None:
    """Update the software version in the device registry."""
    dev_reg = dr.async_get(hass)
    if device := dev_reg.async_get_device_by_identifier(
        (DOMAIN, identifier), config_entry_id
    ):
        if device.sw_version != sw_version:
            dev_reg.async_update_device(device.id, sw_version=sw_version)
