"""Tests for the Tuya Smart Lock data coordinator."""

from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.tuya_smart_lock.const import DOMAIN
from custom_components.tuya_smart_lock.coordinator import TuyaSmartLockCoordinator
from custom_components.tuya_smart_lock.entity import TuyaSmartLockEntity
from custom_components.tuya_smart_lock.errors import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaRateLimitError,
)
from custom_components.tuya_smart_lock.models import TuyaProperty
from custom_components.tuya_smart_lock.tuya_api import TuyaCloudApi

DEVICE_ID = "device-123"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, entry_id="entry-123")


def _coordinator(hass, api: AsyncMock) -> TuyaSmartLockCoordinator:
    return TuyaSmartLockCoordinator(hass, api, DEVICE_ID, _entry())


async def test_successful_refresh_returns_properties(hass) -> None:
    """A successful refresh publishes the normalized property mapping."""
    properties = {
        "lock_motor_state": TuyaProperty(
            code="lock_motor_state",
            value=False,
            timestamp_ms=1_700_000_000_000,
            dp_id=1,
        )
    }
    api = AsyncMock()
    api.async_get_properties.return_value = properties

    coordinator = _coordinator(hass, api)
    await coordinator.async_refresh()

    assert coordinator.data == properties
    assert isinstance(coordinator.data, dict)
    assert coordinator.last_update_success is True
    assert coordinator.config_entry.entry_id == "entry-123"
    assert coordinator.name == DOMAIN
    assert coordinator.update_interval == timedelta(seconds=30)
    api.async_get_properties.assert_awaited_once_with(DEVICE_ID)


async def test_authentication_error_is_sanitized(hass) -> None:
    """Authentication failures request reauthentication without raw details."""
    api = AsyncMock()
    api.async_get_properties.side_effect = TuyaAuthenticationError(
        "secret-token property-value"
    )
    coordinator = _coordinator(hass, api)

    with pytest.raises(
        ConfigEntryAuthFailed, match="^Tuya authentication failed[.]$"
    ) as exc_info:
        await coordinator._async_update_data()

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
    assert "secret-token" not in str(exc_info.value)
    assert "property-value" not in str(exc_info.value)


async def test_non_json_token_outage_is_update_failed_not_auth_failed(
    hass,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Polling maps a token-service outage to an ordinary update failure."""
    aioclient_mock.get(
        "https://openapi.tuyaeu.com/v1.0/token?grant_type=1",
        status=502,
        text="raw outage detail",
    )
    api = TuyaCloudApi(async_get_clientsession(hass), "id", "secret")
    coordinator = _coordinator(hass, api)

    with pytest.raises(UpdateFailed, match="^Unable to update Tuya device data[.]$"):
        await coordinator._async_update_data()


@pytest.mark.parametrize(
    ("error", "message", "retry_after"),
    [
        (
            TuyaAuthorizationError("secret-token property-value"),
            "Tuya API access is not authorized.",
            None,
        ),
        (
            TuyaRateLimitError("secret-token property-value"),
            "Tuya API rate limit exceeded.",
            60,
        ),
        (
            TuyaApiError("secret-token property-value"),
            "Unable to update Tuya device data.",
            None,
        ),
    ],
)
async def test_api_errors_are_sanitized_update_failures(
    hass,
    error: TuyaApiError,
    message: str,
    retry_after: int | None,
) -> None:
    """Operational API failures become fixed, safe update errors."""
    api = AsyncMock()
    api.async_get_properties.side_effect = error
    coordinator = _coordinator(hass, api)

    with pytest.raises(UpdateFailed, match=f"^{message}$") as exc_info:
        await coordinator._async_update_data()

    assert exc_info.value.retry_after == retry_after
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
    assert "secret-token" not in str(exc_info.value)
    assert "property-value" not in str(exc_info.value)


async def test_transient_failure_recovers_and_replaces_data(hass, caplog) -> None:
    """A later successful refresh restores availability and replaces stale data."""
    stale = {
        "battery_percentage": TuyaProperty(
            code="battery_percentage",
            value="property-value",
            timestamp_ms=1_700_000_000_000,
            dp_id=2,
        )
    }
    current = {
        "battery_percentage": TuyaProperty(
            code="battery_percentage",
            value=80,
            timestamp_ms=1_700_000_030_000,
            dp_id=2,
        )
    }
    api = AsyncMock()
    api.async_get_properties.side_effect = [
        stale,
        TuyaApiError("secret-token property-value"),
        current,
    ]
    coordinator = _coordinator(hass, api)

    await coordinator.async_refresh()
    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert coordinator.data == stale
    assert "secret-token" not in caplog.text
    assert "property-value" not in caplog.text

    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.data == current
    assert coordinator.data is not stale


def test_device_sharing_push_replaces_data_without_poll_delay(hass) -> None:
    """Official Tuya MQTT updates reach all entities immediately."""
    api = Mock(name="sharing_api")
    coordinator = _coordinator(hass, api)
    pushed = {
        "doorbell": TuyaProperty(
            code="doorbell",
            value=True,
            timestamp_ms=1_785_000_000_123,
            dp_id=None,
        )
    }

    coordinator.async_handle_push(pushed)

    assert coordinator.data == pushed
    assert coordinator.last_update_success is True


def test_missing_device_push_marks_coordinator_unavailable(hass) -> None:
    """Removing the lock from the official account cannot retain availability."""
    coordinator = _coordinator(hass, Mock(name="sharing_api"))

    coordinator.async_handle_push(None)

    assert coordinator.last_update_success is False


def test_base_entity_has_stable_identity_and_device_info(hass) -> None:
    """The shared entity owns only common identity and device metadata."""
    coordinator = _coordinator(hass, AsyncMock())

    entity = TuyaSmartLockEntity(
        coordinator,
        device_id=DEVICE_ID,
        device_name="Front Door",
        unique_key="battery",
    )

    assert entity.has_entity_name is True
    assert entity.unique_id == f"{DEVICE_ID}_battery"
    assert entity.device_info == {
        "identifiers": {("tuya", DEVICE_ID)},
        "name": "Front Door",
        "manufacturer": "Tuya",
    }
