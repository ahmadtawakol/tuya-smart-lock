"""Adapter for Home Assistant's free Tuya Device Sharing session."""

from collections.abc import Callable, Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from requests import RequestException

from .errors import (
    TuyaApiError,
    TuyaCommandError,
    TuyaDeviceUnavailableError,
)
from .models import TuyaProperty, normalize_timestamp_ms

type SharingUpdateCallback = Callable[[dict[str, TuyaProperty] | None], None]

# Signal published by homeassistant.components.tuya.coordinator.DeviceListener.
TUYA_HA_SIGNAL_UPDATE_ENTITY = "tuya_entry_update"


class TuyaSharingApi:
    """Expose one official Tuya device through the integration API contract."""

    def __init__(
        self,
        hass: HomeAssistant,
        tuya_entry: ConfigEntry[Any],
        device_id: str,
    ) -> None:
        """Initialize a dynamically resolved Device Sharing adapter."""
        self.hass = hass
        self.tuya_entry = tuya_entry
        self.device_id = device_id
        self._timestamps_ms: dict[str, int] = {}

    @property
    def _manager(self) -> Any:
        """Return the latest manager after official Tuya reloads."""
        runtime = getattr(self.tuya_entry, "runtime_data", None)
        manager = getattr(runtime, "manager", None)
        if manager is None:
            raise TuyaApiError("The official Tuya integration is unavailable.")
        return manager

    def _device(self) -> Any:
        """Return the configured shared device without retaining stale objects."""
        device_map = getattr(self._manager, "device_map", None)
        if not isinstance(device_map, Mapping):
            raise TuyaApiError("The official Tuya integration is unavailable.")
        device = device_map.get(self.device_id)
        if device is None:
            raise TuyaDeviceUnavailableError("The Tuya smart lock is unavailable.")
        return device

    def _properties(self) -> dict[str, TuyaProperty]:
        """Normalize cached Device Sharing statuses by code."""
        status = getattr(self._device(), "status", None)
        if not isinstance(status, Mapping):
            return {}
        return {
            code: TuyaProperty(
                code=code,
                value=value,
                timestamp_ms=self._timestamps_ms.get(code),
                dp_id=None,
            )
            for code, value in status.items()
            if isinstance(code, str) and code
        }

    async def async_get_properties(
        self,
        device_id: str,
    ) -> dict[str, TuyaProperty]:
        """Return current properties from the official integration's cache."""
        if device_id != self.device_id:
            raise TuyaDeviceUnavailableError("The Tuya smart lock is unavailable.")
        device = self._device()
        if getattr(device, "online", True) is False:
            raise TuyaDeviceUnavailableError("The Tuya smart lock is unavailable.")
        return self._properties()

    async def async_operate_lock(self, device_id: str, *, open_: bool) -> None:
        """Try the standard writable motor-state datapoint through free sharing."""
        if device_id != self.device_id:
            raise TuyaDeviceUnavailableError("The Tuya smart lock is unavailable.")
        device = self._device()
        if getattr(device, "online", True) is False:
            raise TuyaDeviceUnavailableError("The Tuya smart lock is unavailable.")
        functions = getattr(device, "function", None)
        motor_function = (
            functions.get("lock_motor_state")
            if isinstance(functions, Mapping)
            else None
        )
        if getattr(motor_function, "type", None) != "Boolean":
            raise TuyaCommandError("Tuya lock command failed.")

        try:
            await self.hass.async_add_executor_job(
                self._manager.send_commands,
                self.device_id,
                [{"code": "lock_motor_state", "value": open_}],
            )
        except RequestException, TimeoutError:
            raise TuyaApiError("Unable to communicate with Tuya.") from None
        except Exception as error:
            if error.__class__.__module__.startswith("tuya_sharing"):
                raise TuyaCommandError("Tuya lock command failed.") from None
            raise

    @callback
    def async_subscribe(
        self, update_callback: SharingUpdateCallback
    ) -> Callable[[], None]:
        """Forward official Tuya push updates with their datapoint timestamps."""

        @callback
        def handle_update(
            updated_status_properties: list[str] | None = None,
            dp_timestamps: Mapping[str, object] | None = None,
        ) -> None:
            if dp_timestamps is not None:
                for code, value in dp_timestamps.items():
                    timestamp_ms = normalize_timestamp_ms(value)
                    if isinstance(code, str) and timestamp_ms is not None:
                        self._timestamps_ms[code] = timestamp_ms
            try:
                update_callback(self._properties())
            except TuyaApiError:
                update_callback(None)

        return async_dispatcher_connect(
            self.hass,
            f"{TUYA_HA_SIGNAL_UPDATE_ENTITY}_{self.device_id}",
            handle_update,
        )
