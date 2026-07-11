"""Config flow for Tuya Smart Lock."""

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_API_REGION,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    DOMAIN,
)
from .errors import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaRateLimitError,
)
from .tuya_api import TuyaCloudApi

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
    """Map an API failure to a fixed, user-facing config-flow error."""
    if isinstance(error, TuyaAuthenticationError):
        return "invalid_auth"
    if isinstance(error, TuyaAuthorizationError):
        return "service_not_authorized"
    if isinstance(error, TuyaRateLimitError):
        return "rate_limited"
    return "cannot_connect"


class TuyaSmartLockConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tuya Smart Lock."""

    VERSION = 1

    def __init__(self) -> None:
        self._api: TuyaCloudApi | None = None
        self._credentials: dict[str, str] = {}
        self._discovered_devices: list[dict[str, str]] = []

    def _show_user_form(
        self,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show the credentials form with only fixed error identifiers."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCESS_ID): str,
                    vol.Required(CONF_ACCESS_SECRET): str,
                    vol.Required(CONF_API_REGION, default="eu"): vol.In(REGIONS),
                }
            ),
            errors=errors or {},
        )

    async def async_step_user(self, user_input: dict | None = None):
        """Step 1: Collect Tuya Cloud credentials."""
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
                return self._show_user_form({"base": _flow_error(error)})

            self._api = api
            self._credentials = user_input
            return await self.async_step_select_device()

        return self._show_user_form()

    async def async_step_select_device(self, user_input: dict | None = None):
        """Step 2: Discover and select a lock device."""
        assert self._api is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]

            # Find device name from discovered list
            device_name = device_id
            for device in self._discovered_devices:
                if device["id"] == device_id:
                    device_name = device["name"]
                    break

            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

            # Check remote unlock is enabled
            try:
                remote_ok = await self._api.async_check_remote_unlock(device_id)
            except TuyaAuthenticationError:
                self._api = None
                self._credentials = {}
                self._discovered_devices = []
                return self._show_user_form({"base": "invalid_auth"})
            except _FLOW_EXCEPTIONS as error:
                errors["base"] = _flow_error(error)
            else:
                if remote_ok:
                    return self.async_create_entry(
                        title=device_name,
                        data={
                            CONF_ACCESS_ID: self._credentials[CONF_ACCESS_ID],
                            CONF_ACCESS_SECRET: self._credentials[CONF_ACCESS_SECRET],
                            CONF_API_REGION: self._credentials[CONF_API_REGION],
                            CONF_DEVICE_ID: device_id,
                            CONF_DEVICE_NAME: device_name,
                        },
                    )
                errors["base"] = "remote_unlock_disabled"

        # Discover devices
        if not self._discovered_devices:
            try:
                self._discovered_devices = await self._api.async_discover_devices()
            except _FLOW_EXCEPTIONS as error:
                return self._show_user_form({"base": _flow_error(error)})

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        # Build device selection list
        device_options = {
            device["id"]: f"{device['name']} ({device['category']})"
            for device in self._discovered_devices
        }

        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): vol.In(device_options),
                }
            ),
            errors=errors,
        )
