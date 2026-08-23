"""Config flow for Tuya Smart Lock."""

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_API_REGION,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_TUYA_ENTRY_ID,
    DOMAIN,
    LOCK_CATEGORIES,
)
from .errors import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaRateLimitError,
)
from .tuya_api import TuyaCloudApi

TUYA_DOMAIN = "tuya"

REGIONS = {
    "eu": "Europe",
    "us": "Americas",
    "cn": "China",
    "in": "India",
}

_FLOW_EXCEPTIONS = (
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaRateLimitError,
    TuyaApiError,
    aiohttp.ClientError,
)


def _flow_error(error: Exception) -> str:
    """Map a legacy API failure to a fixed, user-facing config-flow error."""
    if isinstance(error, TuyaAuthenticationError):
        return "invalid_auth"
    if isinstance(error, TuyaAuthorizationError):
        return "service_not_authorized"
    if isinstance(error, TuyaRateLimitError):
        return "rate_limited"
    return "cannot_connect"


class TuyaSmartLockConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up locks from Home Assistant's official Tuya app session."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize transient lock selection state."""
        self._shared_locks: dict[str, tuple[str, Any]] = {}
        self._reconfigure_target: tuple[str, Any] | None = None

    def _discover_shared_locks(self) -> tuple[bool, dict[str, tuple[str, Any]]]:
        """Return locks from loaded official Tuya config entries."""
        loaded_tuya = False
        shared_locks: dict[str, tuple[str, Any]] = {}
        for entry in self.hass.config_entries.async_entries(TUYA_DOMAIN):
            if entry.state is not ConfigEntryState.LOADED:
                continue
            runtime = getattr(entry, "runtime_data", None)
            manager = getattr(runtime, "manager", None)
            device_map = getattr(manager, "device_map", None)
            if not isinstance(device_map, Mapping):
                continue
            loaded_tuya = True
            for device in device_map.values():
                device_id = getattr(device, "id", None)
                category = getattr(device, "category", None)
                if (
                    not isinstance(device_id, str)
                    or not device_id
                    or category not in LOCK_CATEGORIES
                ):
                    continue
                shared_locks[f"{entry.entry_id}:{device_id}"] = (
                    entry.entry_id,
                    device,
                )
        return loaded_tuya, shared_locks

    def _show_reauth_form(
        self,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show replacement credentials for legacy v1.1 entries only."""
        entry = self._get_reauth_entry()
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ACCESS_ID,
                        default=entry.data[CONF_ACCESS_ID],
                    ): str,
                    vol.Required(CONF_ACCESS_SECRET): str,
                    vol.Required(
                        CONF_API_REGION,
                        default=entry.data[CONF_API_REGION],
                    ): vol.In(REGIONS),
                }
            ),
            errors=errors or {},
            description_placeholders={"name": entry.title},
        )

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Discover locks using the official integration's free app login."""
        loaded_tuya, self._shared_locks = self._discover_shared_locks()
        if not loaded_tuya:
            return self.async_abort(reason="tuya_not_configured")
        if not self._shared_locks:
            return self.async_abort(reason="no_devices_found")
        return await self.async_step_select_device()

    async def async_step_select_device(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Select one supported lock from the official Tuya cache."""
        if not self._shared_locks:
            _, self._shared_locks = self._discover_shared_locks()
        if not self._shared_locks:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            selection = user_input[CONF_DEVICE_ID]
            tuya_entry_id, device = self._shared_locks[selection]
            device_id = device.id
            device_name = getattr(device, "name", None) or device_id

            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=device_name,
                data={
                    CONF_TUYA_ENTRY_ID: tuya_entry_id,
                    CONF_DEVICE_ID: device_id,
                    CONF_DEVICE_NAME: device_name,
                },
            )

        device_options = {
            selection: (
                f"{getattr(device, 'name', None) or device.id} "
                f"({getattr(device, 'category', 'lock')})"
            )
            for selection, (_, device) in self._shared_locks.items()
        }
        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEVICE_ID): vol.In(device_options)}
            ),
            errors={},
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """Route reauthentication for sharing and legacy entries."""
        if CONF_TUYA_ENTRY_ID in entry_data:
            tuya_entry = self.hass.config_entries.async_get_entry(
                entry_data[CONF_TUYA_ENTRY_ID]
            )
            if tuya_entry is not None:
                tuya_entry.async_start_reauth(self.hass)
            return self.async_abort(reason="official_tuya_reauth_started")
        return await self.async_step_reauth_confirm()

    async def async_step_reconfigure(
        self,
        entry_data: Mapping[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """Migrate a legacy developer entry to free Device Sharing."""
        entry = self._get_reconfigure_entry()

        if self._reconfigure_target is None:
            loaded_tuya, shared_locks = self._discover_shared_locks()
            if not loaded_tuya:
                return self.async_abort(reason="tuya_not_configured")
            current_device_id = entry.data.get(CONF_DEVICE_ID)
            self._reconfigure_target = next(
                (
                    target
                    for target in shared_locks.values()
                    if getattr(target[1], "id", None) == current_device_id
                ),
                None,
            )
            if self._reconfigure_target is None:
                return self.async_abort(reason="migration_device_not_found")
            if entry.data.get(CONF_TUYA_ENTRY_ID) == self._reconfigure_target[0]:
                return self.async_abort(reason="already_using_official_tuya")

        return await self.async_step_reconfigure_confirm()

    async def async_step_reconfigure_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm removal of legacy developer credentials."""
        entry = self._get_reconfigure_entry()
        if self._reconfigure_target is None:
            return self.async_abort(reason="migration_device_not_found")

        tuya_entry_id, device = self._reconfigure_target
        device_name = getattr(device, "name", None) or device.id
        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data={
                    CONF_TUYA_ENTRY_ID: tuya_entry_id,
                    CONF_DEVICE_ID: device.id,
                    CONF_DEVICE_NAME: device_name,
                },
                reason="reconfigure_successful",
            )

        return self.async_show_form(
            step_id="reconfigure_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"name": device_name},
        )

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Validate replacement credentials for a legacy cloud entry."""
        if user_input is not None:
            api = TuyaCloudApi(
                async_get_clientsession(self.hass),
                access_id=user_input[CONF_ACCESS_ID],
                access_secret=user_input[CONF_ACCESS_SECRET],
                region=user_input[CONF_API_REGION],
            )
            try:
                await api.async_validate_credentials()
            except _FLOW_EXCEPTIONS as error:
                return self._show_reauth_form({"base": _flow_error(error)})

            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data_updates=user_input,
            )

        return self._show_reauth_form()
