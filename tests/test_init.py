"""Tests for Tuya Smart Lock integration setup and unloading."""

from importlib import import_module
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_smart_lock import (
    TuyaSmartLockRuntimeData,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.tuya_smart_lock.const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_API_REGION,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    DOMAIN,
    PLATFORMS,
)

ENTRY_ID = "entry-123"
DEVICE_ID = "device-123"
DEVICE_NAME = "Front Door"
ENTRY_DATA = {
    CONF_ACCESS_ID: "access-id",
    CONF_ACCESS_SECRET: "access-secret",
    CONF_API_REGION: "eu",
    CONF_DEVICE_ID: DEVICE_ID,
    CONF_DEVICE_NAME: DEVICE_NAME,
}
EXPECTED_PLATFORMS = (
    Platform.LOCK,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.EVENT,
)


def _entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        data=ENTRY_DATA,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.mark.parametrize("platform", PLATFORMS)
def test_forwarded_platform_module_is_importable(platform: Platform) -> None:
    """Every platform advertised by setup provides its standard setup hook."""
    module = import_module(
        f"custom_components.tuya_smart_lock.{platform.value}"
    )

    assert callable(module.async_setup_entry)


async def test_setup_uses_shared_session_refreshes_then_forwards(hass) -> None:
    """Setup builds typed runtime data only after a successful first refresh."""
    entry = _entry(hass)
    session = Mock(name="session")
    api = Mock(name="api")
    coordinator = Mock(name="coordinator")
    order: list[str] = []

    async def first_refresh() -> None:
        order.append("refresh")

    async def forward_platforms(forwarded_entry, platforms) -> None:
        order.append("forward")
        assert forwarded_entry is entry
        assert tuple(platforms) == EXPECTED_PLATFORMS
        assert isinstance(
            hass.data[DOMAIN][entry.entry_id], TuyaSmartLockRuntimeData
        )

    coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=first_refresh
    )
    forward = AsyncMock(side_effect=forward_platforms)

    with (
        patch(
            "custom_components.tuya_smart_lock.async_get_clientsession",
            return_value=session,
        ) as get_session,
        patch(
            "custom_components.tuya_smart_lock.TuyaCloudApi", return_value=api
        ) as api_class,
        patch(
            "custom_components.tuya_smart_lock.TuyaSmartLockCoordinator",
            return_value=coordinator,
        ) as coordinator_class,
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=forward,
        ),
    ):
        assert await async_setup_entry(hass, entry) is True

    assert PLATFORMS == EXPECTED_PLATFORMS
    assert order == ["refresh", "forward"]
    get_session.assert_called_once_with(hass)
    api_class.assert_called_once_with(
        session,
        access_id="access-id",
        access_secret="access-secret",
        region="eu",
    )
    coordinator_class.assert_called_once_with(hass, api, DEVICE_ID, entry)
    coordinator.async_config_entry_first_refresh.assert_awaited_once_with()
    forward.assert_awaited_once_with(entry, PLATFORMS)

    runtime = hass.data[DOMAIN][entry.entry_id]
    assert isinstance(runtime, TuyaSmartLockRuntimeData)
    assert runtime.api is api
    assert runtime.coordinator is coordinator
    assert runtime.device_id == DEVICE_ID
    assert runtime.device_name == DEVICE_NAME


async def test_first_refresh_failure_leaves_no_runtime_or_forwarding(hass) -> None:
    """A failed first refresh cannot expose a partial integration runtime."""
    entry = _entry(hass)
    coordinator = Mock(name="coordinator")
    coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=ConfigEntryNotReady("initial refresh failed")
    )
    forward = AsyncMock()

    with (
        patch(
            "custom_components.tuya_smart_lock.async_get_clientsession",
            return_value=Mock(name="session"),
        ),
        patch(
            "custom_components.tuya_smart_lock.TuyaCloudApi",
            return_value=Mock(name="api"),
        ),
        patch(
            "custom_components.tuya_smart_lock.TuyaSmartLockCoordinator",
            return_value=coordinator,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=forward,
        ),
        pytest.raises(ConfigEntryNotReady, match="initial refresh failed"),
    ):
        await async_setup_entry(hass, entry)

    assert entry.entry_id not in hass.data.get(DOMAIN, {})
    forward.assert_not_awaited()


@pytest.mark.parametrize("unload_ok", [True, False])
async def test_unload_removes_runtime_only_on_success(hass, unload_ok: bool) -> None:
    """Unload retains runtime data when any platform fails to unload."""
    entry = _entry(hass)
    runtime = TuyaSmartLockRuntimeData(
        api=Mock(name="api"),
        coordinator=Mock(name="coordinator"),
        device_id=DEVICE_ID,
        device_name=DEVICE_NAME,
    )
    hass.data[DOMAIN] = {entry.entry_id: runtime}
    unload = AsyncMock(return_value=unload_ok)

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=unload,
    ):
        result = await async_unload_entry(hass, entry)

    assert result is unload_ok
    unload.assert_awaited_once_with(entry, PLATFORMS)
    if unload_ok:
        assert entry.entry_id not in hass.data[DOMAIN]
    else:
        assert hass.data[DOMAIN][entry.entry_id] is runtime
