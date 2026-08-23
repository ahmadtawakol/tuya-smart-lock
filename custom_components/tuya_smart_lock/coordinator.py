"""Shared data coordinator for the Tuya Smart Lock integration."""

import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .errors import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaRateLimitError,
)
from .models import TuyaProperty

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=30)


class TuyaLockApi(Protocol):
    """Common contract implemented by paid legacy and free sharing clients."""

    async def async_get_properties(self, device_id: str) -> dict[str, TuyaProperty]: ...

    async def async_operate_lock(self, device_id: str, *, open_: bool) -> None: ...


class TuyaSmartLockCoordinator(DataUpdateCoordinator[dict[str, TuyaProperty]]):
    """Coordinate shared Tuya shadow-property updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TuyaLockApi,
        device_id: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api
        self.device_id = device_id

    @callback
    def async_handle_push(
        self,
        data: Mapping[str, TuyaProperty] | None,
    ) -> None:
        """Publish a Device Sharing push update immediately."""
        if data is None:
            self.async_set_update_error(
                UpdateFailed("Unable to update Tuya device data.")
            )
            return
        self.async_set_updated_data(dict(data))

    async def _async_update_data(self) -> dict[str, TuyaProperty]:
        """Fetch the latest normalized Tuya properties."""
        try:
            return await self.api.async_get_properties(self.device_id)
        except TuyaAuthenticationError:
            raise ConfigEntryAuthFailed("Tuya authentication failed.") from None
        except TuyaAuthorizationError:
            raise UpdateFailed("Tuya API access is not authorized.") from None
        except TuyaRateLimitError:
            raise UpdateFailed(
                "Tuya API rate limit exceeded.", retry_after=60
            ) from None
        except TuyaApiError:
            raise UpdateFailed("Unable to update Tuya device data.") from None
