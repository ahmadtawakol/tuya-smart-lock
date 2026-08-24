"""Tests for the free Tuya Device Sharing adapter."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from homeassistant.helpers.dispatcher import async_dispatcher_send
from tuya_sharing.exceptions import ApiRequestException

from custom_components.tuya_smart_lock.errors import (
    TuyaCommandError,
    TuyaDeviceUnavailableError,
)
from custom_components.tuya_smart_lock.sharing_api import TuyaSharingApi

DEVICE_ID = "lock-123"


def _device(
    *,
    online: bool = True,
    functions: dict | None = None,
    status: dict | None = None,
):
    """Return a minimal Device Sharing lock."""
    return SimpleNamespace(
        id=DEVICE_ID,
        online=online,
        set_up=False,
        support_local=False,
        function=(
            {"lock_motor_state": SimpleNamespace(type="Boolean")}
            if functions is None
            else functions
        ),
        status={"lock_motor_state": False} if status is None else status,
    )


def _api(hass, device=None):
    """Return an adapter backed by a dynamically resolved official runtime."""
    manager = Mock(name="manager")
    manager.device_map = {DEVICE_ID: device or _device()}
    manager.device_repository.query_devices_by_ids.return_value = list(
        manager.device_map.values()
    )
    manager.mq = SimpleNamespace(
        client=Mock(name="mqtt_client"),
        device=list(manager.device_map.values()),
        subscribe_device=Mock(name="subscribe_device"),
    )
    official_entry = SimpleNamespace(
        entry_id="official-tuya-entry",
        runtime_data=SimpleNamespace(manager=manager),
    )
    return TuyaSharingApi(hass, official_entry, DEVICE_ID), manager, official_entry


async def test_properties_are_read_from_official_device_cache(hass) -> None:
    """Free mode normalizes the official integration's cached statuses."""
    api, _, _ = _api(
        hass,
        _device(status={"lock_motor_state": False, "residual_electricity": 73}),
    )

    properties = await api.async_get_properties(DEVICE_ID)

    assert properties["lock_motor_state"].value is False
    assert properties["residual_electricity"].value == 73
    assert properties["lock_motor_state"].timestamp_ms is None
    assert properties["lock_motor_state"].dp_id is None


async def test_command_uses_standard_device_sharing_datapoint(hass) -> None:
    """Free control sends the motor state as an ordinary Tuya command."""
    api, manager, _ = _api(hass)

    await api.async_operate_lock(DEVICE_ID, open_=True)

    manager.send_commands.assert_called_once_with(
        DEVICE_ID,
        [{"code": "lock_motor_state", "value": True}],
    )


@pytest.mark.parametrize(
    ("device", "error_type"),
    [
        (_device(online=False), TuyaDeviceUnavailableError),
        (_device(functions={}), TuyaCommandError),
        (
            _device(functions={"lock_motor_state": SimpleNamespace(type="Raw")}),
            TuyaCommandError,
        ),
    ],
    ids=["offline", "motor-state-not-writable", "motor-state-not-boolean"],
)
async def test_command_rejects_unsafe_or_unsupported_devices(
    hass, device, error_type
) -> None:
    """No command is sent unless the lock is online and declares the DP writable."""
    api, manager, _ = _api(hass, device)

    with pytest.raises(error_type):
        await api.async_operate_lock(DEVICE_ID, open_=False)

    manager.send_commands.assert_not_called()


async def test_sdk_command_error_is_sanitized(hass, caplog) -> None:
    """Raw Device Sharing failures never cross the integration boundary."""
    api, manager, _ = _api(hass)
    manager.send_commands.side_effect = ApiRequestException(
        error_code="permission-denied",
        error_message="raw-account-and-lock-detail",
    )

    with pytest.raises(TuyaCommandError, match="Tuya lock command failed") as error:
        await api.async_operate_lock(DEVICE_ID, open_=True)

    assert "raw-account" not in str(error.value)
    assert "raw-account" not in caplog.text


async def test_stream_source_uses_official_tuya_allocator(hass) -> None:
    """Camera streaming reuses the free app-authenticated manager."""
    api, manager, _ = _api(hass)
    manager.get_device_stream_allocate.return_value = (
        "rtsp://temporary-user:temporary-token@camera.example/stream"
    )

    source = await api.async_get_stream_source(DEVICE_ID, "rtsp")

    assert source == "rtsp://temporary-user:temporary-token@camera.example/stream"
    manager.get_device_stream_allocate.assert_called_once_with(DEVICE_ID, "rtsp")


@pytest.mark.parametrize("result", [None, "", 123])
async def test_invalid_stream_allocation_returns_none(hass, result) -> None:
    """Malformed stream responses cannot leak into Home Assistant or FFmpeg."""
    api, manager, _ = _api(hass)
    manager.get_device_stream_allocate.return_value = result

    assert await api.async_get_stream_source(DEVICE_ID, "rtsp") is None


async def test_adapter_resolves_reloaded_official_manager(hass) -> None:
    """Official Tuya reloads replace the manager without requiring our reload."""
    api, old_manager, official_entry = _api(hass)
    new_manager = Mock(name="new_manager")
    new_manager.device_map = {DEVICE_ID: _device(status={"lock_motor_state": True})}
    new_manager.device_repository.query_devices_by_ids.return_value = list(
        new_manager.device_map.values()
    )
    new_manager.mq = SimpleNamespace(
        client=Mock(name="new_mqtt_client"),
        device=list(new_manager.device_map.values()),
        subscribe_device=Mock(name="new_subscribe_device"),
    )
    official_entry.runtime_data = SimpleNamespace(manager=new_manager)

    properties = await api.async_get_properties(DEVICE_ID)

    assert properties["lock_motor_state"].value is True
    old_manager.send_commands.assert_not_called()


async def test_missing_device_is_unavailable(hass) -> None:
    """Removing the shared lock cannot leave stale controllable state."""
    api, manager, _ = _api(hass)
    manager.device_map = {}

    with pytest.raises(TuyaDeviceUnavailableError):
        await api.async_get_properties(DEVICE_ID)


async def test_offline_cache_is_refreshed_without_reloading_official_tuya(
    hass,
) -> None:
    """A targeted query replaces stale offline metadata in the cached object."""
    cached = _device(online=False, status={"lock_motor_state": False})
    fresh = _device(
        online=True,
        status={"lock_motor_state": False, "residual_electricity": 68},
    )
    api, manager, _ = _api(hass, cached)
    manager.device_repository.query_devices_by_ids.return_value = [fresh]

    properties = await api.async_get_properties(DEVICE_ID)

    manager.device_repository.query_devices_by_ids.assert_called_once_with([DEVICE_ID])
    assert manager.device_map[DEVICE_ID] is cached
    assert cached.online is True
    assert properties["residual_electricity"].value == 68


async def test_prepare_subscribes_unsupported_lock_device_topic_once(hass) -> None:
    """The custom lock receives online and event pushes despite no core entity."""
    cached = _device()
    api, manager, _ = _api(hass, cached)
    manager.device_repository.query_devices_by_ids.return_value = [_device()]
    manager.mq = SimpleNamespace(
        client=Mock(name="mqtt_client"),
        device=[],
        subscribe_device=Mock(name="subscribe_device"),
    )

    await api.async_prepare()
    await api.async_prepare()

    assert cached.set_up is True
    manager.mq.subscribe_device.assert_called_once_with(DEVICE_ID, cached)


async def test_official_push_preserves_event_timestamp(hass) -> None:
    """Push timestamps reach event entities without replaying initial values."""
    api, manager, _ = _api(
        hass,
        _device(status={"lock_motor_state": False, "doorbell": True}),
    )
    updates = []
    unsubscribe = api.async_subscribe(updates.append)

    async_dispatcher_send(
        hass,
        f"tuya_entry_update_{DEVICE_ID}",
        ["doorbell"],
        {"doorbell": 1_785_000_000_123},
    )
    await hass.async_block_till_done()

    assert len(updates) == 1
    assert updates[0]["doorbell"].timestamp_ms == 1_785_000_000_123
    unsubscribe()
    manager.send_commands.assert_not_called()


async def test_offline_and_online_pushes_update_availability_without_reload(
    hass,
) -> None:
    """Direct device-topic presence updates recover the coordinator immediately."""
    device = _device(online=False)
    api, _, _ = _api(hass, device)
    updates = []
    unsubscribe = api.async_subscribe(updates.append)

    async_dispatcher_send(
        hass,
        f"tuya_entry_update_{DEVICE_ID}",
        None,
        None,
    )
    device.online = True
    async_dispatcher_send(
        hass,
        f"tuya_entry_update_{DEVICE_ID}",
        None,
        None,
    )
    await hass.async_block_till_done()

    assert updates[0] is None
    assert updates[1]["lock_motor_state"].value is False
    unsubscribe()


async def test_missing_sdk_timestamp_gets_monotonic_receipt_time(hass) -> None:
    """Code-based Tuya reports still produce repeatable event occurrences."""
    device = _device(status={"unlock_fingerprint": 7})
    api, _, _ = _api(hass, device)
    updates = []
    unsubscribe = api.async_subscribe(updates.append)

    with patch(
        "custom_components.tuya_smart_lock.sharing_api.time.time",
        return_value=1_785_000_000.123,
    ):
        async_dispatcher_send(
            hass,
            f"tuya_entry_update_{DEVICE_ID}",
            ["unlock_fingerprint"],
            {},
        )
        async_dispatcher_send(
            hass,
            f"tuya_entry_update_{DEVICE_ID}",
            ["unlock_fingerprint"],
            {},
        )
        await hass.async_block_till_done()

    first = updates[0]["unlock_fingerprint"].timestamp_ms
    second = updates[1]["unlock_fingerprint"].timestamp_ms
    assert first == 1_785_000_000_123
    assert second == first + 1
    unsubscribe()


async def test_invalid_sdk_event_timestamp_falls_back_to_receipt_time(hass) -> None:
    """Malformed optional SDK metadata cannot suppress a real event report."""
    api, _, _ = _api(hass, _device(status={"doorbell": True}))
    updates = []
    unsubscribe = api.async_subscribe(updates.append)

    with patch(
        "custom_components.tuya_smart_lock.sharing_api.time.time",
        return_value=1_785_000_000.456,
    ):
        async_dispatcher_send(
            hass,
            f"tuya_entry_update_{DEVICE_ID}",
            ["doorbell"],
            {"doorbell": "not-a-timestamp"},
        )
        await hass.async_block_till_done()

    assert updates[0]["doorbell"].timestamp_ms == 1_785_000_000_456
    unsubscribe()


async def test_multi_event_snapshot_does_not_replay_historical_events(hass) -> None:
    """One bulk refresh cannot emit every stale lock event simultaneously."""
    device = _device(
        status={
            "doorbell": True,
            "open_inside": True,
            "unlock_face": 3,
        }
    )
    api, _, _ = _api(hass, device)
    updates = []
    with patch(
        "custom_components.tuya_smart_lock.sharing_api.monotonic",
        return_value=100.0,
    ):
        unsubscribe = api.async_subscribe(updates.append)
        async_dispatcher_send(
            hass,
            f"tuya_entry_update_{DEVICE_ID}",
            ["doorbell", "open_inside", "unlock_face"],
            {
                "doorbell": 1_784_000_000_001,
                "open_inside": 1_784_000_000_002,
                "unlock_face": 1_784_000_000_003,
            },
        )
        await hass.async_block_till_done()

    assert updates[0]["doorbell"].timestamp_ms is None
    assert updates[0]["open_inside"].timestamp_ms is None
    assert updates[0]["unlock_face"].timestamp_ms is None
    unsubscribe()


async def test_live_doorbell_and_open_batch_emits_both_events(hass) -> None:
    """A later real-world multi-event report is not mistaken for a snapshot."""
    device = _device(status={"doorbell": True, "open_inside": True})
    api, _, _ = _api(hass, device)
    updates = []

    with (
        patch(
            "custom_components.tuya_smart_lock.sharing_api.monotonic",
            side_effect=[100.0, 110.0],
        ),
        patch(
            "custom_components.tuya_smart_lock.sharing_api.time.time",
            return_value=1_785_000_000.789,
        ),
    ):
        unsubscribe = api.async_subscribe(updates.append)
        async_dispatcher_send(
            hass,
            f"tuya_entry_update_{DEVICE_ID}",
            ["doorbell", "open_inside"],
            {},
        )
        await hass.async_block_till_done()

    assert updates[0]["doorbell"].timestamp_ms == 1_785_000_000_789
    assert updates[0]["open_inside"].timestamp_ms == 1_785_000_000_789
    unsubscribe()
