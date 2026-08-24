"""Tuya Smart Lock integration."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_API_REGION,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_TUYA_ENTRY_ID,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import TuyaLockApi, TuyaSmartLockCoordinator
from .sharing_api import TuyaSharingApi
from .tuya_api import TuyaCloudApi


@dataclass(frozen=True, slots=True)
class TuyaSmartLockRuntimeData:
    """Typed runtime state shared by Tuya Smart Lock platforms."""

    api: TuyaLockApi
    coordinator: TuyaSmartLockCoordinator
    device_id: str
    device_name: str
    unsubscribe: Callable[[], None] | None = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tuya Smart Lock from a config entry."""
    device_id = entry.data[CONF_DEVICE_ID]
    device_name = entry.data[CONF_DEVICE_NAME]
    sharing_entry_id = entry.data.get(CONF_TUYA_ENTRY_ID)
    sharing_api: TuyaSharingApi | None = None
    if isinstance(sharing_entry_id, str):
        official_entry = hass.config_entries.async_get_entry(sharing_entry_id)
        if (
            official_entry is None
            or official_entry.state is not ConfigEntryState.LOADED
            or getattr(getattr(official_entry, "runtime_data", None), "manager", None)
            is None
        ):
            raise ConfigEntryNotReady("The official Tuya integration is not loaded.")
        sharing_api = TuyaSharingApi(hass, official_entry, device_id)
        await sharing_api.async_prepare()
        api: TuyaLockApi = sharing_api
    else:
        session = async_get_clientsession(hass)
        api = TuyaCloudApi(
            session,
            access_id=entry.data[CONF_ACCESS_ID],
            access_secret=entry.data[CONF_ACCESS_SECRET],
            region=entry.data[CONF_API_REGION],
        )
    coordinator = TuyaSmartLockCoordinator(hass, api, device_id, entry)

    unsubscribe = (
        api.async_subscribe(coordinator.async_handle_push)
        if isinstance(sharing_entry_id, str)
        else None
    )
    setup_complete = False
    try:
        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryNotReady:
            if sharing_api is None:
                raise
            coordinator.async_set_updated_data(sharing_api.cached_properties())
            coordinator.async_set_update_error(
                UpdateFailed("The Tuya smart lock is offline.")
            )
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = TuyaSmartLockRuntimeData(
            api=api,
            coordinator=coordinator,
            device_id=device_id,
            device_name=device_name,
            unsubscribe=unsubscribe,
        )
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        setup_complete = True
    finally:
        if not setup_complete:
            hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
            if unsubscribe is not None:
                unsubscribe()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime = hass.data[DOMAIN].pop(entry.entry_id, None)
        if runtime is not None and runtime.unsubscribe is not None:
            runtime.unsubscribe()
    return unload_ok
