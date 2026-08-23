"""Tests for the free Tuya Device Sharing adapter."""

from types import SimpleNamespace
from unittest.mock import Mock

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


async def test_adapter_resolves_reloaded_official_manager(hass) -> None:
    """Official Tuya reloads replace the manager without requiring our reload."""
    api, old_manager, official_entry = _api(hass)
    new_manager = Mock(name="new_manager")
    new_manager.device_map = {DEVICE_ID: _device(status={"lock_motor_state": True})}
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
