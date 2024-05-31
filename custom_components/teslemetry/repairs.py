from __future__ import annotations

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.helpers import issue_registry as ir
from homeassistant.core import HomeAssistant
from tesla_fleet_api.exceptions import (
    SubscriptionRequired,
    Forbidden,
    LoginRequired
)

class SubscriptionRepairFlow(RepairsFlow):
    """Handler for an issue fixing flow."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step of a fix flow."""

        return await (self.async_step_confirm())

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the confirm step of a fix flow."""
        if user_input is not None:
            return self.async_create_entry(title="Fixed", data={})

        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
) -> RepairsFlow:
    """Create flow."""
    if(issue_id == SubscriptionRequired.key):
        return SubscriptionRepairFlow()
    elif(issue_id == Forbidden.key):
        return SubscriptionRepairFlow()
    elif(issue_id == LoginRequired.key):
        return SubscriptionRepairFlow()