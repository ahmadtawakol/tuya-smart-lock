"""Tuya Smart Lock integration."""

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_API_REGION,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import TuyaSmartLockCoordinator
from .tuya_api import TuyaCloudApi


@dataclass(frozen=True, slots=True)
class TuyaSmartLockRuntimeData:
    """Typed runtime state shared by Tuya Smart Lock platforms."""

    api: TuyaCloudApi
    coordinator: TuyaSmartLockCoordinator
    device_id: str
    device_name: str


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tuya Smart Lock from a config entry."""
    session = async_get_clientsession(hass)
    api = TuyaCloudApi(
        session,
        access_id=entry.data[CONF_ACCESS_ID],
        access_secret=entry.data[CONF_ACCESS_SECRET],
        region=entry.data[CONF_API_REGION],
    )
    device_id = entry.data[CONF_DEVICE_ID]
    device_name = entry.data[CONF_DEVICE_NAME]
    coordinator = TuyaSmartLockCoordinator(hass, api, device_id, entry)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = TuyaSmartLockRuntimeData(
        api=api,
        coordinator=coordinator,
        device_id=device_id,
        device_name=device_name,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
