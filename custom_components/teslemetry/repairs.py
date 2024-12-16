"""Teslemetry Repairs."""
from __future__ import annotations


from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from tesla_fleet_api.exceptions import TeslaFleetError

class SubscriptionRepairFlow(RepairsFlow):
    """Handler for an issue fixing flow."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step of a fix flow."""

        return self.async_show_form(step_id="confirm")

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the confirm step of a fix flow."""

        for vehicle in self.entry.runtime_data.vehicles:
            if vehicle.vin == self.key:
                try:
                    await self.entry.runtime_data.teslemetry.test()
                except TeslaFleetError:
                    # Not fixed
                    return self.async_show_form(step_id="confirm")

                # Fixed
                await self.hass.config_entries.async_reload(self.entry.entry_id)
                return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
) -> RepairsFlow:
    """Create flow."""
    if(issue_id == "subscription_required"):
        return SubscriptionRepairFlow()
    elif(issue_id == "unauthorized missing scopes"):
        return SubscriptionRepairFlow()
    elif(issue_id == "login_required"):
        return SubscriptionRepairFlow()
