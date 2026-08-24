"""Tests for the experimental Device Sharing camera entity."""

import logging
from unittest.mock import AsyncMock, Mock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_smart_lock import TuyaSmartLockRuntimeData
from custom_components.tuya_smart_lock import camera as camera_platform
from custom_components.tuya_smart_lock.const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_TUYA_ENTRY_ID,
    DOMAIN,
)
from custom_components.tuya_smart_lock.errors import TuyaApiError
from custom_components.tuya_smart_lock.models import TuyaProperty

ENTRY_ID = "entry-123"
DEVICE_ID = "lock-123"
DEVICE_NAME = "Front Door"


async def _setup_camera(hass, *, sharing: bool = True):
    """Set up the camera platform with sharing or legacy runtime data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        data={
            CONF_DEVICE_ID: DEVICE_ID,
            CONF_DEVICE_NAME: DEVICE_NAME,
            **({CONF_TUYA_ENTRY_ID: "official-tuya-entry"} if sharing else {}),
        },
    )
    api = Mock(name="api")
    api.async_get_stream_source = AsyncMock()
    coordinator = Mock(name="coordinator")
    coordinator.last_update_success = True
    coordinator.data = {}
    coordinator.async_add_listener.return_value = Mock(name="remove_listener")
    hass.data[DOMAIN] = {
        ENTRY_ID: TuyaSmartLockRuntimeData(
            api=api,
            coordinator=coordinator,
            device_id=DEVICE_ID,
            device_name=DEVICE_NAME,
        )
    }
    add_entities = Mock()

    await camera_platform.async_setup_entry(hass, entry, add_entities)
    return api, add_entities


async def test_sharing_setup_adds_one_stream_camera(hass) -> None:
    """Free Device Sharing entries expose one privacy-safe camera entity."""
    api, add_entities = await _setup_camera(hass)

    add_entities.assert_called_once()
    entity = add_entities.call_args.args[0][0]
    assert entity.unique_id == f"{DEVICE_ID}_camera"
    assert entity.supported_features == camera_platform.CameraEntityFeature.STREAM
    assert entity.device_info["identifiers"] == {("tuya", DEVICE_ID)}
    assert entity.should_poll is False
    assert entity.api is api


async def test_legacy_cloud_entry_does_not_add_unsupported_camera(hass) -> None:
    """The legacy ticket API has no free stream allocator."""
    _, add_entities = await _setup_camera(hass, sharing=False)

    add_entities.assert_not_called()


async def test_stream_source_delegates_without_exposing_url_as_state(hass) -> None:
    """Temporary authenticated stream URLs remain inside the camera pipeline."""
    api, add_entities = await _setup_camera(hass)
    entity = add_entities.call_args.args[0][0]
    api.async_get_stream_source.return_value = "rtsp://temporary/secret"

    assert await entity.stream_source() == "rtsp://temporary/secret"
    api.async_get_stream_source.assert_awaited_once_with(DEVICE_ID, "rtsp")
    assert "secret" not in repr(entity.device_info)


async def test_stream_source_falls_back_across_tuya_formats(hass) -> None:
    """A video lock that rejects RTSP can still provide HLS or another format."""
    api, add_entities = await _setup_camera(hass)
    entity = add_entities.call_args.args[0][0]
    api.async_get_stream_source.side_effect = [
        TuyaApiError("safe RTSP rejection"),
        None,
        "flv://temporary/stream",
    ]

    assert await entity.stream_source() == "flv://temporary/stream"
    assert api.async_get_stream_source.await_args_list == [
        ((DEVICE_ID, "rtsp"),),
        ((DEVICE_ID, "hls"),),
        ((DEVICE_ID, "flv"),),
    ]


async def test_camera_image_uses_home_assistant_ffmpeg(hass) -> None:
    """Snapshots are extracted on demand without persisting image bytes."""
    api, add_entities = await _setup_camera(hass)
    entity = add_entities.call_args.args[0][0]
    entity.hass = hass
    api.async_get_stream_source.return_value = "rtsp://temporary/stream"

    with patch(
        "custom_components.tuya_smart_lock.camera.ffmpeg.async_get_image",
        new=AsyncMock(return_value=b"jpeg-bytes"),
    ) as get_image:
        image = await entity.async_camera_image(width=640, height=360)

    assert image == b"jpeg-bytes"
    get_image.assert_awaited_once_with(
        hass,
        "rtsp://temporary/stream",
        width=640,
        height=360,
    )


async def test_missing_stream_returns_no_snapshot_with_one_safe_warning(
    hass, caplog
) -> None:
    """An unsupported video lock returns no image and no credential detail."""
    api, add_entities = await _setup_camera(hass)
    entity = add_entities.call_args.args[0][0]
    entity.hass = hass
    api.async_get_stream_source.return_value = None

    with patch(
        "custom_components.tuya_smart_lock.camera.ffmpeg.async_get_image",
        new=AsyncMock(),
    ) as get_image:
        assert await entity.async_camera_image() is None
        assert await entity.async_camera_image() is None

    get_image.assert_not_awaited()
    assert caplog.text.count("Tuya did not provide a supported camera stream") == 1
    assert "rtsp://" not in caplog.text


async def test_existing_doorbell_state_is_seeded_without_capture(hass) -> None:
    """Historical doorbell state cannot take a camera image on startup."""
    api, add_entities = await _setup_camera(hass)
    entity = add_entities.call_args.args[0][0]
    entity.hass = hass
    entity.coordinator.data = {"doorbell": TuyaProperty("doorbell", True, 100, None)}

    await entity.async_added_to_hass()
    await hass.async_block_till_done()

    api.async_get_stream_source.assert_not_awaited()
    assert entity.extra_state_attributes["last_event_snapshot_status"] == "idle"


async def test_new_doorbell_event_caches_one_in_memory_snapshot(hass, caplog) -> None:
    """A real ring automatically probes and retains a private JPEG in memory."""
    api, add_entities = await _setup_camera(hass)
    entity = add_entities.call_args.args[0][0]
    entity.hass = hass
    entity.async_write_ha_state = Mock()
    await entity.async_added_to_hass()
    api.async_get_stream_source.return_value = "rtsp://temporary/stream"

    with (
        caplog.at_level(logging.INFO),
        patch(
            "custom_components.tuya_smart_lock.camera.ffmpeg.async_get_image",
            new=AsyncMock(return_value=b"doorbell-jpeg"),
        ) as get_image,
    ):
        entity.coordinator.data = {
            "doorbell": TuyaProperty("doorbell", True, 101, None)
        }
        entity._handle_coordinator_update()
        await hass.async_block_till_done()

    assert entity.extra_state_attributes["last_event_snapshot_status"] == "captured"
    assert entity.extra_state_attributes["last_event_snapshot_at"] is not None
    assert await entity.async_camera_image() == b"doorbell-jpeg"
    get_image.assert_awaited_once()
    assert "Captured Tuya doorbell camera snapshot" in caplog.text
    assert "rtsp://" not in caplog.text


async def test_doorbell_probe_reports_no_authorized_stream_safely(hass, caplog) -> None:
    """The unattended test leaves a fixed actionable result without secrets."""
    api, add_entities = await _setup_camera(hass)
    entity = add_entities.call_args.args[0][0]
    entity.hass = hass
    entity.async_write_ha_state = Mock()
    await entity.async_added_to_hass()
    api.async_get_stream_source.return_value = None

    entity.coordinator.data = {"doorbell": TuyaProperty("doorbell", True, 101, None)}
    entity._handle_coordinator_update()
    await hass.async_block_till_done()

    assert entity.extra_state_attributes["last_event_snapshot_status"] == (
        "stream_unavailable"
    )
    assert "Tuya doorbell snapshot test found no supported stream" in caplog.text
    assert "token" not in caplog.text
