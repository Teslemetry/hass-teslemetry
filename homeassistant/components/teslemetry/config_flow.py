"""Config Flow for Teslemetry integration."""

import asyncio
from collections.abc import Mapping
from http import HTTPStatus
import logging
from pathlib import Path
from typing import Any, cast, override

from aiohttp import ClientError
from aiopowerwall import (
    DEFAULT_GATEWAY_HOST,
    PowerwallAuthenticationError,
    PowerwallClient,
    PowerwallError,
)
from bleak.exc import BleakError
from tesla_fleet_api.const import (
    AuthorizedClientKeyType,
    AuthorizedClientState,
    AuthorizedClientType,
)
from tesla_fleet_api.exceptions import (
    BluetoothTimeout,
    BluetoothTransportError,
    InvalidToken,
    NotOnWhitelistFault,
    SubscriptionRequired,
    TeslaFleetError,
    TeslemetryRegistrationError,
    WhitelistOperationAttemptingToAddExistingKey,
)
from tesla_fleet_api.tesla import EnergySiteRouter
from tesla_fleet_api.tesla.vehicle.bluetooth import VehicleBluetooth
from tesla_fleet_api.teslemetry import Teslemetry
from tesla_fleet_api.teslemetry.energysite import AuthorizedClient, TeslemetryEnergySite
import voluptuous as vol

from homeassistant.components.bluetooth import (
    async_discovered_service_info,
    async_request_active_scan,
)
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_ADDRESS, CONF_HOST, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from . import TeslemetryConfigEntry
from .const import (
    CONF_SITE_ID,
    CONF_VIN,
    DOMAIN,
    LOGGER,
    POWERWALL_KEY_FILE,
    SUBENTRY_TYPE_ENERGY_SITE,
    SUBENTRY_TYPE_VEHICLE,
)
from .helpers import async_get_ble_parent
from .logship import CONF_SHIP_LOGS_TO_CLICKSTACK
from .models import TeslemetryEnergyData
from .oauth import async_ensure_client_credential


class PowerwallUnreachableError(Exception):
    """Signal that an energy gateway-relay command returned HTTP 502.

    The Teslemetry API returns 502 Bad Gateway on gateway-relay commands when the
    customer's Powerwall gateway is unreachable (for example it has dropped off
    the network). This is a retryable upstream condition, distinct from an
    ordinary API failure.
    """


class PowerwallLookupError(Exception):
    """Signal that the authorized-client lookup failed for a non-retryable reason."""


class PowerwallKeyRejectedError(Exception):
    """Signal that the gateway refused a v1r-signed read with our RSA key."""


_PENDING_STATES = (AuthorizedClientState.PENDING_VERIFICATION,)


def _cloud_energy_site(energy_data: TeslemetryEnergyData) -> TeslemetryEnergySite:
    """Return the cloud energy-site API for pairing.

    Pairing always talks to the Teslemetry cloud to register the key; when a site
    is already paired its api is an EnergySiteRouter, so unwrap the cloud
    secondary rather than the local Powerwall primary.
    """
    return cast(
        TeslemetryEnergySite,
        energy_data.api.secondary
        if isinstance(energy_data.api, EnergySiteRouter)
        else energy_data.api,
    )


def _is_gateway_unreachable(err: TeslaFleetError | ClientError) -> bool:
    """Return whether err is a 502 Bad Gateway from an energy gateway command.

    A bodyless 502 surfaces from tesla-fleet-api as a TeslaFleetError carrying
    status; a 502 with a JSON body surfaces as aiohttp.ClientResponseError.
    status is read with getattr since neither is guaranteed to carry one.
    """
    return getattr(err, "status", None) == HTTPStatus.BAD_GATEWAY


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Config flow to handle Teslemetry OAuth2 authentication."""

    DOMAIN = DOMAIN
    VERSION = 2

    def __init__(self) -> None:
        """Initialize config flow."""
        super().__init__()
        self.data: dict[str, Any] = {}
        self.uid: str | None = None

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: TeslemetryConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return TeslemetryOptionsFlowHandler()

    @property
    @override
    def logger(self) -> logging.Logger:
        """Return logger."""
        return LOGGER

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types supported by this integration."""
        return {
            SUBENTRY_TYPE_VEHICLE: VehicleSubentryFlowHandler,
            SUBENTRY_TYPE_ENERGY_SITE: EnergySiteSubentryFlowHandler,
        }

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow start."""
        try:
            await async_ensure_client_credential(self.hass)
        except TeslemetryRegistrationError:
            return self.async_show_form(
                step_id="user",
                errors={"base": "cannot_connect"},
            )
        return await super().async_step_user()

    @override
    async def async_oauth_create_entry(
        self,
        data: dict[str, Any],
    ) -> ConfigFlowResult:
        """Handle OAuth completion and create config entry."""
        self.data = data

        # Test the connection with the OAuth token
        errors = await self.async_test_connection(data)
        if errors:
            return self.async_abort(reason="oauth_error")

        await self.async_set_unique_id(self.uid)
        # When the entry is loaded its subentry-change update listener applies the
        # new token via a reload, so use the non-reloading variant to avoid a double
        # reload and the paired-reload deprecation warning. When it is not loaded
        # (e.g. reauth after a setup failure) no listener exists, so the reloading
        # variant is needed to apply the data and emits no deprecation.
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="reauth_account_mismatch")
            entry = self._get_reauth_entry()
            if entry.state is ConfigEntryState.LOADED:
                return self.async_update_and_abort(entry, data=data)
            return self.async_update_reload_and_abort(entry, data=data)
        if self.source == SOURCE_RECONFIGURE:
            self._abort_if_unique_id_mismatch(reason="reconfigure_account_mismatch")
            entry = self._get_reconfigure_entry()
            if entry.state is ConfigEntryState.LOADED:
                return self.async_update_and_abort(entry, data=data)
            return self.async_update_reload_and_abort(entry, data=data)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title="Teslemetry",
            data=data,
        )

    async def async_test_connection(self, token_data: dict[str, Any]) -> dict[str, str]:
        """Test the connection with OAuth token."""
        access_token = token_data["token"]["access_token"]

        teslemetry = Teslemetry(
            session=async_get_clientsession(self.hass),
            access_token=access_token,
        )

        try:
            metadata = await teslemetry.metadata()
        except InvalidToken:
            return {"base": "invalid_access_token"}
        except SubscriptionRequired:
            return {"base": "subscription_required"}
        except ClientError:
            return {"base": "cannot_connect"}
        except TeslaFleetError as e:
            LOGGER.error("Teslemetry API error: %s", e)
            return {"base": "unknown"}

        self.uid = metadata["uid"]
        return {}

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauth on failure."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauth dialog."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                description_placeholders={"name": "Teslemetry"},
            )

        return await super().async_step_user()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        return await self.async_step_user()


class TeslemetryOptionsFlowHandler(OptionsFlow):
    """Options flow for the Teslemetry integration (HACS-only)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the durable ClickStack log shipping opt-in."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SHIP_LOGS_TO_CLICKSTACK,
                        default=self.config_entry.options.get(
                            CONF_SHIP_LOGS_TO_CLICKSTACK, False
                        ),
                    ): BooleanSelector(),
                }
            ),
        )


class VehicleSubentryFlowHandler(ConfigSubentryFlow):
    """Add local Bluetooth control to one of the account's vehicles."""

    def __init__(self) -> None:
        """Initialize the vehicle subentry flow."""
        self._vin: str | None = None
        self._title: str | None = None
        self._address: str | None = None
        self._vehicle: VehicleBluetooth | None = None
        self._pair_task: asyncio.Task[None] | None = None
        self._pair_error: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Select an account vehicle to add over Bluetooth, then pair it."""
        entry = self._get_entry()
        already_added = {
            subentry.data[CONF_VIN]
            for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_VEHICLE)
            if CONF_VIN in subentry.data
        }
        # The account's vehicles come from runtime data; a paired vehicle uses
        # the same existing device, so no new device is created here.
        choices = {
            vehicle.vin: vehicle.device["name"] or vehicle.vin
            for vehicle in entry.runtime_data.vehicles
            if vehicle.vin not in already_added
        }
        if not choices:
            return self.async_abort(reason="no_vehicles")

        if user_input is not None:
            self._vin = user_input[CONF_VIN]
            self._title = choices[self._vin]
            return await self.async_step_scan()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_VIN): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=vin, label=name)
                                for vin, name in choices.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Re-run Bluetooth pairing for an already added vehicle."""
        self._vin = self._get_reconfigure_subentry().data[CONF_VIN]
        return await self.async_step_scan()

    async def async_step_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Find the vehicle over Bluetooth and connect to it."""
        assert self._vin is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            parent = await async_get_ble_parent(self.hass)
            # The advertised BLE name is a hash of the VIN; match on its prefix.
            expected = parent.get_name(self._vin)[:17]
            device = None
            # The name is only in scan responses, so an AUTO-mode scanner that
            # has not swept recently may not have it cached yet.
            await async_request_active_scan(self.hass)
            for info in async_discovered_service_info(self.hass, connectable=True):
                if info.name and info.name.startswith(expected):
                    device = info.device
                    self._address = info.address
                    break

            if device is None:
                errors["base"] = "device_not_found"
            else:
                # Keep the default keepalive here (unlike command routing): it
                # holds the link through the on-screen key-approval wait so the
                # whitelist reply is not lost to a link-supervision drop.
                self._vehicle = parent.vehicles.createBluetooth(
                    self._vin, device=device
                )
                try:
                    await self._vehicle.connect()
                except (BleakError, TeslaFleetError, TimeoutError) as err:
                    LOGGER.error("Failed to connect over Bluetooth: %s", err)
                    await self._async_disconnect()
                    errors["base"] = "cannot_connect"
                else:
                    return await self.async_step_pair()

        return self.async_show_form(
            step_id="scan",
            errors=errors,
            description_placeholders={"vin": self._vin},
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Check whether the virtual key is already whitelisted on the vehicle."""
        assert self._vehicle is not None
        try:
            await self._vehicle.handshakeVehicleSecurity()
        except NotOnWhitelistFault:
            return await self.async_step_instructions()
        except TeslaFleetError as err:
            LOGGER.error("Bluetooth security handshake failed: %s", err)
            return await self._async_abort("cannot_connect")
        return await self._async_finish()

    async def async_step_instructions(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask the user to approve the virtual key on the vehicle touchscreen."""
        if user_input is not None:
            return await self.async_step_authorize()
        errors = self._pair_error
        self._pair_error = {}
        return self.async_show_form(
            step_id="instructions",
            errors=errors,
            description_placeholders={"vin": self._vin or ""},
        )

    async def async_step_authorize(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add the virtual key to the vehicle while showing pairing progress."""
        if self._pair_task is None:
            assert self._vehicle is not None
            # pair() writes the whitelist op exactly once and confirms completion
            # by reply or key-state polling, so it is never re-sent (which would
            # re-prompt the user). It can take minutes, so run it as a progress
            # task rather than blocking the flow request.
            self._pair_task = self.hass.async_create_task(self._vehicle.pair())

        if not self._pair_task.done():
            return self.async_show_progress(
                step_id="authorize",
                progress_action="pair",
                progress_task=self._pair_task,
                description_placeholders={"vin": self._vin or ""},
            )

        task = self._pair_task
        self._pair_task = None
        try:
            task.result()
        except (BluetoothTransportError, BleakError) as err:
            # The link dropped before the key could be confirmed - a transport
            # failure, not the user failing to approve in time.
            LOGGER.debug("Bluetooth transport failed during pairing: %s", err)
            self._pair_error = {"base": "cannot_connect"}
            return self.async_show_progress_done(next_step_id="instructions")
        except (BluetoothTimeout, TimeoutError) as err:
            # The key was sent but the vehicle never confirmed - the user has not
            # approved it yet.
            LOGGER.debug("Bluetooth pairing timed out: %s", err)
            self._pair_error = {"base": "timeout"}
            return self.async_show_progress_done(next_step_id="instructions")
        except WhitelistOperationAttemptingToAddExistingKey as err:
            # The key is already on the whitelist, so pairing has succeeded: the
            # vehicle reports this once the user approves a key whose earlier
            # add attempt went unconfirmed. Re-handshake to confirm it.
            LOGGER.debug("Virtual key is already on the whitelist: %s", err)
        except TeslaFleetError as err:
            # The vehicle rejected the key (e.g. whitelist full, denied on the
            # screen, or valet mode) - not a timeout the user can wait out.
            LOGGER.error("Bluetooth pairing was rejected: %s", err)
            self._pair_error = {"base": "pair_failed"}
            return self.async_show_progress_done(next_step_id="instructions")
        return self.async_show_progress_done(next_step_id="pair")

    async def _async_finish(self) -> SubentryFlowResult:
        """Persist the paired BLE address, deferring the reload to the subentry-change listener so setup sees the committed address."""
        assert self._address is not None
        assert self._vin is not None
        await self._async_disconnect()
        entry = self._get_entry()
        if self.source == SOURCE_RECONFIGURE:
            result = self.async_update_and_abort(
                entry,
                self._get_reconfigure_subentry(),
                data_updates={CONF_ADDRESS: self._address},
            )
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return result
        return self.async_create_entry(
            title=self._title or self._vin,
            data={CONF_VIN: self._vin, CONF_ADDRESS: self._address},
            unique_id=self._vin,
        )

    async def _async_abort(self, reason: str) -> SubentryFlowResult:
        """Disconnect any open BLE connection and abort the flow."""
        await self._async_disconnect()
        return self.async_abort(reason=reason)

    async def _async_disconnect(self) -> None:
        """Disconnect the BLE link, if any, and drop the reference to it."""
        vehicle = self._vehicle
        self._vehicle = None
        if vehicle is not None:
            try:
                await vehicle.disconnect()
            except (BleakError, TeslaFleetError, TimeoutError) as err:
                LOGGER.debug("Error disconnecting Bluetooth: %s", err)

    @callback
    @override
    def async_remove(self) -> None:
        """Release resources if the flow is abandoned mid-pairing."""
        if self._pair_task is not None and not self._pair_task.done():
            self._pair_task.cancel()
        if self._vehicle is not None:
            self.hass.async_create_task(self._async_disconnect())


class EnergySiteSubentryFlowHandler(ConfigSubentryFlow):
    """Pair a local Powerwall gateway for TEDAPI v1r command routing."""

    def __init__(self) -> None:
        """Initialize the energy site subentry flow."""
        self._energy_site: TeslemetryEnergySite | None = None
        self._key_pem: bytes | None = None
        self._public_key_der: bytes = b""
        self._public_key_b64: str = ""
        self._discovered_host: str = ""
        self._site_id: int | None = None
        self._site_name: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Let the user opt an account energy site into local Powerwall control."""
        entry = cast(TeslemetryConfigEntry, self._get_entry())
        # runtime_data (the resolved energy sites) only exists while the entry is
        # loaded; core clears it on unload, so bail out cleanly if it is not.
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        added_site_ids = {
            subentry.unique_id
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_ENERGY_SITE
        }
        available = {
            str(energy_data.id): energy_data
            for energy_data in entry.runtime_data.energysites
            if energy_data.can_local_control
            and str(energy_data.id) not in added_site_ids
        }
        if not available:
            return self.async_abort(reason="no_energy_sites")

        if user_input is not None:
            energy_data = available[user_input[CONF_SITE_ID]]
            self._site_id = energy_data.id
            self._site_name = energy_data.device.get("name") or "Energy Site"
            await self._prepare_energy_site(_cloud_energy_site(energy_data))
            return await self._async_begin_pairing()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SITE_ID): vol.In(
                        {
                            site_id: energy_data.device.get("name") or site_id
                            for site_id, energy_data in available.items()
                        }
                    )
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Look up the site's cloud API and start (or resume) key pairing."""
        subentry = self._get_reconfigure_subentry()
        entry = cast(TeslemetryConfigEntry, self._get_entry())
        # runtime_data (the resolved energy sites) only exists while the entry is
        # loaded; core clears it on unload, so bail out cleanly if it is not.
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")
        energy_data = next(
            (
                energysite
                for energysite in entry.runtime_data.energysites
                if energysite.subentry_id == subentry.subentry_id
            ),
            None,
        )
        if energy_data is None:
            return self.async_abort(reason="cannot_connect")
        self._site_id = energy_data.id
        self._site_name = energy_data.device.get("name") or "Energy Site"
        await self._prepare_energy_site(_cloud_energy_site(energy_data))
        return await self._async_begin_pairing()

    async def _prepare_energy_site(self, energy_site: TeslemetryEnergySite) -> None:
        """Discover the gateway address and load the integration's RSA key."""
        self._energy_site = energy_site

        try:
            self._discovered_host = await energy_site.find_gateway_address() or ""
        except (ClientError, TeslaFleetError) as err:
            LOGGER.warning(
                "Gateway address discovery failed, prompting for manual entry: %s", err
            )
            self._discovered_host = ""
        else:
            if not self._discovered_host:
                LOGGER.warning(
                    "Gateway address discovery returned no address, prompting for manual entry"
                )

        path = self.hass.config.path(POWERWALL_KEY_FILE)
        keyholder = Teslemetry(
            session=async_get_clientsession(self.hass), access_token=""
        )
        await keyholder.get_rsa_private_key(path)
        self._key_pem = await self.hass.async_add_executor_job(Path(path).read_bytes)
        self._public_key_der = keyholder.rsa_public_der_pkcs1
        self._public_key_b64 = keyholder.rsa_public_der_pkcs1_b64

    async def _async_begin_pairing(self) -> SubentryFlowResult:
        """Resume or begin key pairing based on the key's state on the gateway."""
        try:
            client = await self._find_authorized_client()
        except PowerwallUnreachableError:
            return self.async_abort(reason="powerwall_unreachable")
        except PowerwallLookupError:
            return self.async_abort(reason="cannot_connect")
        if client is not None:
            # The key is already registered on the gateway. If it is verified,
            # move on to credentials; if it is still pending, resume approval
            # without re-registering it (re-adding would reset a pending key).
            if client.state == AuthorizedClientState.VERIFIED:
                return await self.async_step_credentials()
            if client.state in _PENDING_STATES:
                return await self.async_step_pair()
            if client.state == AuthorizedClientState.PENDING_VERIFICATION_TIMEOUT:
                # The approval window expired; offer to request a new one
                # in-place rather than sending the user back to setup.
                return await self.async_step_retry()
            # The typed accessor preserves an unrecognized state verbatim. Such
            # a read is not usable, so treat it as a lookup failure rather than
            # resuming pairing on a state we cannot reason about.
            LOGGER.debug("Unrecognized authorized-client state: %s", client.state)
            return self.async_abort(reason="cannot_connect")

        return await self._register_authorized_client()

    async def _register_authorized_client(self) -> SubentryFlowResult:
        """Push our key to the gateway to open an approval window, then wait.

        Shared by the initial registration and the retry step; re-registering
        requests a fresh approval window and resumes the verification wait.
        """
        assert self._energy_site is not None
        try:
            # Not revoked on removal by design; see the class docstring.
            LOGGER.info("Powerwall key setup: id=%s", self._energy_site.energy_site_id)
            await self._energy_site.add_authorized_client(
                self._public_key_der,
                description="Home Assistant",
                key_type=AuthorizedClientKeyType.RSA,
                authorized_client_type=AuthorizedClientType.CUSTOMER_MOBILE_APP,
            )
        except (ClientError, TeslaFleetError) as err:
            if _is_gateway_unreachable(err):
                return self.async_abort(reason="powerwall_unreachable")
            LOGGER.error("Add authorized client failed: %s", err)
            return self.async_abort(reason="cannot_connect")

        return await self.async_step_pair()

    async def async_step_retry(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Offer to request a new approval window after the previous one expired.

        On submit, re-registers the key to open a fresh approval window and
        resumes the verification wait, exactly as the first attempt does.
        """
        if user_input is None:
            return self.async_show_form(step_id="retry")
        return await self._register_authorized_client()

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Check once whether the pending key has been approved on the gateway."""
        assert self._energy_site is not None
        if user_input is None:
            return self.async_show_form(step_id="pair")

        try:
            client = await self._find_authorized_client()
        except PowerwallUnreachableError:
            return self.async_show_form(
                step_id="pair", errors={"base": "powerwall_unreachable"}
            )
        except PowerwallLookupError:
            return self.async_show_form(
                step_id="pair", errors={"base": "cannot_connect"}
            )

        if client is None:
            return self.async_show_form(
                step_id="pair", errors={"base": "key_not_registered"}
            )
        if client.state == AuthorizedClientState.VERIFIED:
            return await self.async_step_credentials()
        if client.state == AuthorizedClientState.PENDING_VERIFICATION:
            return self.async_show_form(step_id="pair", errors={"base": "key_pending"})
        if client.state == AuthorizedClientState.PENDING_VERIFICATION_TIMEOUT:
            # The approval window expired; offer to request a new one in-place
            # rather than re-submitting this form forever.
            return await self.async_step_retry()
        # Only an explicit PENDING_VERIFICATION may claim the approval is still
        # awaiting the user; an unrecognized state is a failed read, and
        # reporting it as pending would trap the user in the form retrying forever.
        LOGGER.debug("Unrecognized authorized-client state: %s", client.state)
        return self.async_show_form(step_id="pair", errors={"base": "cannot_connect"})

    async def _find_authorized_client(self) -> AuthorizedClient | None:
        """Return our RSA key's authorized-client entry on the gateway, or None."""
        assert self._energy_site is not None
        try:
            result = await self._energy_site.find_authorized_clients()
        except (ClientError, TeslaFleetError) as err:
            # A 502 is a reachable-cloud/unreachable-gateway condition the user
            # can retry; any other failure means no usable client list, so raise
            # rather than mistaking it for an unregistered key and re-registering
            # it (which would reset an already pending key).
            if _is_gateway_unreachable(err):
                raise PowerwallUnreachableError from err
            LOGGER.debug("find_authorized_clients failed: %s", err)
            raise PowerwallLookupError from err
        return next(
            (
                client
                for client in result.clients
                if client.public_key == self._public_key_b64
            ),
            None,
        )

    async def _verify_local_gateway(self, host: str, password: str) -> None:
        """Prove the LAN connection and the RSA key against the gateway."""
        assert self._key_pem is not None
        assert self._energy_site is not None
        async with PowerwallClient(
            host=host,
            gateway_password=password,
            rsa_private_key_pem=self._key_pem,
            session=async_get_clientsession(self.hass),
        ) as client:
            await client.connect()
            try:
                # connect() already passed the password login, so a failure here
                # is the unapproved RSA key rejecting the signed read, not a bad
                # password.
                await client.get_status()
            except PowerwallAuthenticationError as err:
                raise PowerwallKeyRejectedError from err

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Collect the local gateway host/password and verify the LAN connection."""
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._energy_site is not None
            host = user_input[CONF_HOST].strip()
            # The Powerwall gateway login accepts only the last 5 characters of
            # the Wi-Fi password printed on the gateway; users routinely enter
            # the full string, so trim it to what the gateway will accept.
            password = user_input[CONF_PASSWORD].strip()[-5:]
            try:
                await self._verify_local_gateway(host, password)
            except PowerwallKeyRejectedError as err:
                LOGGER.debug("Powerwall rejected the signed read: %s", err.__cause__)
                errors["base"] = "key_not_approved"
            except PowerwallAuthenticationError:
                errors["base"] = "invalid_password"
            except PowerwallError as err:
                LOGGER.debug("Local Powerwall verify failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return self._async_save_credentials(host, password)

        # Only pre-fill the host when discovery actually found it. A failed
        # discovery leaves the field blank so the setup-AP default is never
        # presented as if it were the discovered address.
        host_key = (
            vol.Required(CONF_HOST, default=self._discovered_host)
            if self._discovered_host
            else vol.Required(CONF_HOST)
        )

        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema(
                {
                    host_key: str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            description_placeholders={"ap_address": DEFAULT_GATEWAY_HOST},
            errors=errors,
        )

    @callback
    def _async_save_credentials(self, host: str, password: str) -> SubentryFlowResult:
        """Persist the verified gateway credentials to the subentry.

        Creates a new subentry bound to the selected site during the add flow, or
        updates the existing one during reconfigure. Either way the parent entry
        reloads (via its update listener) so the site starts routing locally.
        """
        if self.source == SOURCE_RECONFIGURE:
            # The unified subentry-change listener reacts to a subentry's data
            # changing, so persisting the new credentials is enough to reload the
            # entry and re-point the site at its gateway.
            self._async_update(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data_updates={CONF_HOST: host, CONF_PASSWORD: password},
            )
            return self.async_abort(reason="reconfigure_successful")

        return self.async_create_entry(
            title=self._site_name,
            data={
                CONF_SITE_ID: self._site_id,
                CONF_HOST: host,
                CONF_PASSWORD: password,
            },
            unique_id=str(self._site_id),
        )
