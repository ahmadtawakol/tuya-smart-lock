"""Adapter for Home Assistant's free Tuya Device Sharing session."""

import time
from asyncio import Lock
from collections.abc import Callable, Mapping
from time import monotonic
from typing import Any, Literal

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from requests import RequestException

from .const import EVENT_SOURCE_CODES
from .errors import (
    TuyaApiError,
    TuyaCommandError,
    TuyaDeviceUnavailableError,
)
from .models import TuyaProperty, normalize_timestamp_ms

type SharingUpdateCallback = Callable[[dict[str, TuyaProperty] | None], None]

# Signal published by homeassistant.components.tuya.coordinator.DeviceListener.
TUYA_HA_SIGNAL_UPDATE_ENTITY = "tuya_entry_update"
OFFLINE_REFRESH_INTERVAL_SECONDS = 10
EVENT_SNAPSHOT_GRACE_SECONDS = 5


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
        self._refresh_lock = Lock()
        self._last_device_refresh = 0.0
        self._prepared_manager: Any = None

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

    def cached_properties(self) -> dict[str, TuyaProperty]:
        """Return retained state even while the physical lock is offline."""
        return self._properties()

    async def _async_sdk_call(self, target: Callable[..., Any], *args: Any) -> Any:
        """Run one blocking Device Sharing call behind a sanitized boundary."""
        try:
            return await self.hass.async_add_executor_job(target, *args)
        except RequestException, TimeoutError:
            raise TuyaApiError("Unable to communicate with Tuya.") from None
        except Exception as error:
            if error.__class__.__module__.startswith("tuya_sharing"):
                raise TuyaApiError("Unable to communicate with Tuya.") from None
            raise

    async def _async_refresh_device(self) -> Any:
        """Refresh only this lock and update the cached object in place."""
        async with self._refresh_lock:
            manager = self._manager
            repository = getattr(manager, "device_repository", None)
            query_devices = getattr(repository, "query_devices_by_ids", None)
            if not callable(query_devices):
                raise TuyaApiError("The official Tuya integration is unavailable.")
            devices = await self._async_sdk_call(query_devices, [self.device_id])

            if not isinstance(devices, list):
                raise TuyaApiError("The official Tuya integration is unavailable.")
            fresh = next(
                (
                    device
                    for device in devices
                    if getattr(device, "id", None) == self.device_id
                ),
                None,
            )
            if fresh is None:
                raise TuyaDeviceUnavailableError("The Tuya smart lock is unavailable.")

            device_map = getattr(manager, "device_map", None)
            if not isinstance(device_map, dict):
                raise TuyaApiError("The official Tuya integration is unavailable.")
            cached = device_map.get(self.device_id)
            if cached is None:
                device_map[self.device_id] = fresh
                cached = fresh
            else:
                for name, value in vars(fresh).items():
                    if name != "set_up":
                        setattr(cached, name, value)
            self._last_device_refresh = monotonic()
            return cached

    async def async_prepare(self) -> None:
        """Refresh and subscribe unsupported locks to their direct MQTT topic."""
        device = await self._async_refresh_device()
        manager = self._manager
        device.set_up = True
        if self._prepared_manager is manager:
            return

        mq = getattr(manager, "mq", None)
        if mq is None or getattr(mq, "client", None) is None:
            await self._async_sdk_call(manager.refresh_mq)
            self._prepared_manager = manager
            return

        subscribed_devices = getattr(mq, "device", []) or []
        if not any(
            getattr(subscribed, "id", None) == self.device_id
            for subscribed in subscribed_devices
        ):
            await self._async_sdk_call(
                mq.subscribe_device,
                self.device_id,
                device,
            )
        self._prepared_manager = manager

    async def async_get_properties(
        self,
        device_id: str,
    ) -> dict[str, TuyaProperty]:
        """Return current properties from the official integration's cache."""
        if device_id != self.device_id:
            raise TuyaDeviceUnavailableError("The Tuya smart lock is unavailable.")
        device = self._device()
        if self._prepared_manager is not self._manager:
            await self.async_prepare()
            device = self._device()
        if getattr(device, "online", True) is False:
            if (
                monotonic() - self._last_device_refresh
                >= OFFLINE_REFRESH_INTERVAL_SECONDS
            ):
                device = await self._async_refresh_device()
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

    async def async_get_stream_source(
        self,
        device_id: str,
        stream_type: Literal["flv", "hls", "rtmp", "rtsp"] = "rtsp",
    ) -> str | None:
        """Allocate a temporary camera stream through Device Sharing."""
        await self.async_get_properties(device_id)
        allocator = getattr(self._manager, "get_device_stream_allocate", None)
        if not callable(allocator):
            raise TuyaApiError("Tuya camera streaming is unavailable.")
        source = await self._async_sdk_call(
            allocator,
            self.device_id,
            stream_type,
        )
        return source if isinstance(source, str) and source else None

    @callback
    def async_subscribe(
        self, update_callback: SharingUpdateCallback
    ) -> Callable[[], None]:
        """Forward official Tuya push updates with their datapoint timestamps."""
        subscribed_at = monotonic()

        @callback
        def handle_update(
            updated_status_properties: list[str] | None = None,
            dp_timestamps: Mapping[str, object] | None = None,
        ) -> None:
            updated_codes = {
                code
                for code in updated_status_properties or []
                if isinstance(code, str)
            }
            normalized_timestamps = {
                code: timestamp_ms
                for code, value in (dp_timestamps or {}).items()
                if isinstance(code, str)
                and (timestamp_ms := normalize_timestamp_ms(value)) is not None
            }
            timestamp_codes = set(normalized_timestamps)
            event_codes = (updated_codes | timestamp_codes) & EVENT_SOURCE_CODES
            ambiguous_event_snapshot = (
                len(event_codes) > 1
                and monotonic() - subscribed_at <= EVENT_SNAPSHOT_GRACE_SECONDS
            )

            for code, timestamp_ms in normalized_timestamps.items():
                if ambiguous_event_snapshot and code in EVENT_SOURCE_CODES:
                    continue
                self._timestamps_ms[code] = timestamp_ms

            if not ambiguous_event_snapshot:
                received_ms = int(time.time() * 1000)
                for event_code in sorted(event_codes - timestamp_codes):
                    self._timestamps_ms[event_code] = max(
                        received_ms,
                        self._timestamps_ms.get(event_code, -1) + 1,
                    )
            try:
                if getattr(self._device(), "online", True) is False:
                    update_callback(None)
                else:
                    update_callback(self._properties())
            except TuyaApiError:
                update_callback(None)

        return async_dispatcher_connect(
            self.hass,
            f"{TUYA_HA_SIGNAL_UPDATE_ENTITY}_{self.device_id}",
            handle_update,
        )
