"""Config flow for Opower integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from opower import (
    CannotConnect,
    InvalidAuth,
    Opower,
    create_cookie_jar,
    get_supported_utility_names,
    select_utility,
)
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import VolDictType

from .const import CONF_TOTP_SECRET, CONF_UTILITY, DOMAIN

_LOGGER = logging.getLogger(__name__)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_UTILITY): vol.In(get_supported_utility_names()),
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _validate_login(
    hass: HomeAssistant, login_data: dict[str, str]
) -> dict[str, str]:
    """Validate login data and return any errors."""
    api = Opower(
        async_create_clientsession(hass, cookie_jar=create_cookie_jar()),
        login_data[CONF_UTILITY],
        login_data[CONF_USERNAME],
        login_data[CONF_PASSWORD],
        login_data.get(CONF_TOTP_SECRET),
    )
    errors: dict[str, str] = {}
    try:
        await api.async_login()
    except InvalidAuth:
        _LOGGER.exception(
            "Invalid auth when connecting to %s", login_data[CONF_UTILITY]
        )
        errors["base"] = "invalid_auth"
    except CannotConnect:
        _LOGGER.exception("Could not connect to %s", login_data[CONF_UTILITY])
        errors["base"] = "cannot_connect"
    return errors


class OpowerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Opower."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize a new OpowerConfigFlow."""
        self.utility_info: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match(
                {
                    CONF_UTILITY: user_input[CONF_UTILITY],
                    CONF_USERNAME: user_input[CONF_USERNAME],
                }
            )
            if select_utility(user_input[CONF_UTILITY]).accepts_mfa():
                self.utility_info = user_input
                return await self.async_step_mfa()

            errors = await _validate_login(self.hass, user_input)
            if not errors:
                return self._async_create_opower_entry(user_input)
        else:
            user_input = {}
        user_input.pop(CONF_PASSWORD, None)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_mfa(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle MFA step."""
        assert self.utility_info is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**self.utility_info, **user_input}
            errors = await _validate_login(self.hass, data)
            if not errors:
                return self._async_create_opower_entry(data)

        if errors:
            schema = {
                vol.Required(
                    CONF_USERNAME, default=self.utility_info[CONF_USERNAME]
                ): str,
                vol.Required(CONF_PASSWORD): str,
            }
        else:
            schema = {}

        schema[vol.Required(CONF_TOTP_SECRET)] = str

        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    @callback
    def _async_create_opower_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Create the config entry."""
        return self.async_create_entry(
            title=f"{data[CONF_UTILITY]} ({data[CONF_USERNAME]})",
            data=data,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle configuration by re-auth."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog that informs the user that reauth is required."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**reauth_entry.data, **user_input}
            errors = await _validate_login(self.hass, data)
            if not errors:
                return self.async_update_reload_and_abort(reauth_entry, data=data)

        schema: VolDictType = {
            vol.Required(CONF_USERNAME): reauth_entry.data[CONF_USERNAME],
            vol.Required(CONF_PASSWORD): str,
        }
        if select_utility(reauth_entry.data[CONF_UTILITY]).accepts_mfa():
            schema[vol.Optional(CONF_TOTP_SECRET)] = str
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={CONF_NAME: reauth_entry.title},
        )
