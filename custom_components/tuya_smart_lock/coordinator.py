"""Shared data coordinator for the Tuya Smart Lock integration."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
from .tuya_api import TuyaCloudApi

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=30)


class TuyaSmartLockCoordinator(DataUpdateCoordinator[dict[str, TuyaProperty]]):
    """Coordinate shared Tuya shadow-property updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TuyaCloudApi,
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
