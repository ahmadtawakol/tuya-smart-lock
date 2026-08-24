"""Experimental camera support for Tuya video locks."""

import logging
from asyncio import Lock
from typing import cast

from homeassistant.components import ffmpeg
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TuyaSmartLockRuntimeData
from .const import CONF_TUYA_ENTRY_ID, DOMAIN
from .coordinator import TuyaSmartLockCoordinator
from .entity import TuyaSmartLockEntity
from .errors import TuyaApiError
from .sharing_api import TuyaSharingApi

_LOGGER = logging.getLogger(__name__)
STREAM_TYPES = ("rtsp", "hls", "flv", "rtmp")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add a camera only for free Device Sharing entries."""
    if CONF_TUYA_ENTRY_ID not in entry.data:
        return
    runtime: TuyaSmartLockRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TuyaSmartLockCamera(
                runtime.coordinator,
                cast(TuyaSharingApi, runtime.api),
                device_id=runtime.device_id,
                device_name=runtime.device_name,
            )
        ]
    )


class TuyaSmartLockCamera(TuyaSmartLockEntity, Camera):
    """Represent the single stream allocated for a Tuya video lock."""

    _attr_translation_key = "camera"
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: TuyaSmartLockCoordinator,
        api: TuyaSharingApi,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the camera without retaining stream credentials."""
        super().__init__(
            coordinator,
            device_id=device_id,
            device_name=device_name,
            unique_key="camera",
        )
        Camera.__init__(self)
        self.api = api
        self._device_id = device_id
        self._stream_failure_reported = False
        self._last_doorbell_timestamp_ms: int | None = None
        self._last_event_image: bytes | None = None
        self._last_event_snapshot_status = "idle"
        self._last_event_snapshot_at: str | None = None
        self._capture_lock = Lock()

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Expose only safe doorbell-probe status, never URLs or image bytes."""
        return {
            "last_event_snapshot_status": self._last_event_snapshot_status,
            "last_event_snapshot_at": self._last_event_snapshot_at,
        }

    def _doorbell_timestamp_ms(self) -> int | None:
        """Return a valid current doorbell occurrence timestamp."""
        if not self.coordinator.data:
            return None
        prop = self.coordinator.data.get("doorbell")
        if prop is None or type(prop.timestamp_ms) is not int:
            return None
        return prop.timestamp_ms if prop.timestamp_ms >= 0 else None

    async def async_added_to_hass(self) -> None:
        """Seed the event cursor so historical doorbells do not capture."""
        await super().async_added_to_hass()
        self._last_doorbell_timestamp_ms = self._doorbell_timestamp_ms()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Schedule one private in-memory snapshot for each new doorbell."""
        timestamp_ms = self._doorbell_timestamp_ms()
        if timestamp_ms is not None and (
            self._last_doorbell_timestamp_ms is None
            or timestamp_ms > self._last_doorbell_timestamp_ms
        ):
            self._last_doorbell_timestamp_ms = timestamp_ms
            self.hass.async_create_task(
                self._async_capture_doorbell_snapshot(),
                "Tuya doorbell camera snapshot",
            )
        super()._handle_coordinator_update()

    async def stream_source(self) -> str | None:
        """Return a fresh temporary RTSP stream URL."""
        for stream_type in STREAM_TYPES:
            try:
                source = await self.api.async_get_stream_source(
                    self._device_id,
                    stream_type,
                )
            except TuyaApiError:
                continue
            if source is not None:
                self._stream_failure_reported = False
                return source
        if not self._stream_failure_reported:
            _LOGGER.warning(
                "Tuya did not provide a supported camera stream for this video lock"
            )
            self._stream_failure_reported = True
        return None

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return the last event image, or extract a fresh on-demand JPEG."""
        if self._last_event_image is not None:
            return self._last_event_image
        return await self._async_fetch_image(width=width, height=height)

    async def _async_fetch_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Extract a fresh JPEG from the temporary stream."""
        source = await self.stream_source()
        if source is None:
            return None
        return await ffmpeg.async_get_image(
            self.hass,
            source,
            width=width,
            height=height,
        )

    async def _async_capture_doorbell_snapshot(self) -> None:
        """Run an unattended doorbell stream test and retain no persistent data."""
        async with self._capture_lock:
            self._last_event_image = None
            self._last_event_snapshot_status = "capturing"
            self._last_event_snapshot_at = dt_util.utcnow().isoformat(
                timespec="seconds"
            )
            self.async_write_ha_state()
            status = "capture_failed"
            try:
                image = await self._async_fetch_image()
            except Exception:
                image = None
                _LOGGER.warning("Tuya doorbell snapshot test could not decode stream")
            else:
                if image is None:
                    status = "stream_unavailable"
                    _LOGGER.warning(
                        "Tuya doorbell snapshot test found no supported stream"
                    )
                else:
                    status = "captured"
                    self._last_event_image = image
                    _LOGGER.info("Captured Tuya doorbell camera snapshot")
            self._last_event_snapshot_status = status
            self.async_write_ha_state()
