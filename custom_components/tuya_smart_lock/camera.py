"""Experimental camera support for Tuya video locks."""

import logging
from typing import cast

from homeassistant.components import ffmpeg
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TuyaSmartLockRuntimeData
from .const import CONF_TUYA_ENTRY_ID, DOMAIN
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
        coordinator,
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
        """Extract an on-demand JPEG from the temporary stream."""
        source = await self.stream_source()
        if source is None:
            return None
        return await ffmpeg.async_get_image(
            self.hass,
            source,
            width=width,
            height=height,
        )
