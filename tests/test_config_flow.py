"""Tests for the Tuya Smart Lock config flow."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_platform,
)

from custom_components.tuya_smart_lock import config_flow
from custom_components.tuya_smart_lock.const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_API_REGION,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    DOMAIN,
)
from custom_components.tuya_smart_lock.errors import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaRateLimitError,
)

ACCESS_ID = "test-access-id"
ACCESS_SECRET = "highly-sensitive-access-secret"
DEVICE_ID = "lock-123"
DEVICE_NAME = "Front Door"
CREDENTIALS = {
    CONF_ACCESS_ID: ACCESS_ID,
    CONF_ACCESS_SECRET: ACCESS_SECRET,
    CONF_API_REGION: "eu",
}
DEVICE = {
    "id": DEVICE_ID,
    "name": DEVICE_NAME,
    "category": "videolock",
    "model": "",
    "product_name": "",
}


def _api() -> Mock:
    """Return a mocked Tuya API with async setup methods."""
    api = Mock(name="tuya_api")
    api.async_validate_credentials = AsyncMock()
    api.async_discover_devices = AsyncMock(return_value=[DEVICE])
    api.async_check_remote_unlock = AsyncMock(return_value=True)
    return api


async def _start_flow(hass):
    """Start the user config flow."""
    mock_platform(
        hass,
        f"{DOMAIN}.config_flow",
        config_flow,
        built_in=False,
    )
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
    )


async def _submit_credentials(hass, api: Mock):
    """Start the flow and submit standard credentials with a mocked API."""
    session = Mock(name="shared_session")
    with (
        patch(
            "custom_components.tuya_smart_lock.config_flow.async_get_clientsession",
            return_value=session,
        ) as get_session,
        patch(
            "custom_components.tuya_smart_lock.config_flow.TuyaCloudApi",
            return_value=api,
        ) as api_class,
    ):
        initial = await _start_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            initial["flow_id"],
            user_input=CREDENTIALS,
        )
    return result, session, get_session, api_class


async def test_user_step_shows_credentials_form(hass) -> None:
    """The flow starts with the Tuya credential form."""
    result = await _start_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    assert (
        result["data_schema"](
            {
                CONF_ACCESS_ID: ACCESS_ID,
                CONF_ACCESS_SECRET: ACCESS_SECRET,
            }
        )
        == CREDENTIALS
    )


async def test_valid_credentials_discover_and_configure_selected_lock(
    hass, caplog
) -> None:
    """A valid selected lock creates a uniquely identified config entry."""
    api = _api()
    calls: list[str] = []

    async def validate() -> None:
        calls.append("validate")

    async def discover() -> list[dict[str, str]]:
        calls.append("discover")
        return [DEVICE]

    async def check_remote_unlock(device_id: str) -> bool:
        assert device_id == DEVICE_ID
        calls.append("check_remote_unlock")
        return True

    api.async_validate_credentials.side_effect = validate
    api.async_discover_devices.side_effect = discover
    api.async_check_remote_unlock.side_effect = check_remote_unlock

    result, session, get_session, api_class = await _submit_credentials(hass, api)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_device"
    assert result["errors"] == {}
    assert result["data_schema"]({CONF_DEVICE_ID: DEVICE_ID}) == {
        CONF_DEVICE_ID: DEVICE_ID
    }
    with pytest.raises(vol.Invalid):
        result["data_schema"]({CONF_DEVICE_ID: "not-discovered"})
    assert calls == ["validate", "discover"]
    get_session.assert_called_once_with(hass)
    api_class.assert_called_once_with(
        session,
        access_id=ACCESS_ID,
        access_secret=ACCESS_SECRET,
        region="eu",
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_DEVICE_ID: DEVICE_ID},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == DEVICE_NAME
    assert result["data"] == {
        CONF_ACCESS_ID: ACCESS_ID,
        CONF_ACCESS_SECRET: ACCESS_SECRET,
        CONF_API_REGION: "eu",
        CONF_DEVICE_ID: DEVICE_ID,
        CONF_DEVICE_NAME: DEVICE_NAME,
    }
    assert result["result"].unique_id == DEVICE_ID
    assert calls == ["validate", "discover", "check_remote_unlock"]
    api.async_validate_credentials.assert_awaited_once_with()
    api.async_discover_devices.assert_awaited_once_with()
    api.async_check_remote_unlock.assert_awaited_once_with(DEVICE_ID)
    assert ACCESS_SECRET not in result["title"]
    assert ACCESS_SECRET not in caplog.text


@pytest.mark.parametrize(
    ("error", "flow_error"),
    [
        (TuyaAuthenticationError("raw secret detail"), "invalid_auth"),
        (
            TuyaAuthorizationError("raw secret detail"),
            "service_not_authorized",
        ),
        (TuyaRateLimitError("raw secret detail"), "rate_limited"),
        (TuyaApiError("raw secret detail"), "cannot_connect"),
        (aiohttp.ClientError("raw secret detail"), "cannot_connect"),
    ],
    ids=["authentication", "authorization", "rate-limit", "api", "aiohttp"],
)
async def test_credential_failure_shows_actionable_safe_error(
    hass, caplog, error: Exception, flow_error: str
) -> None:
    """Credential failures stay on the user form with a fixed safe error."""
    api = _api()
    api.async_validate_credentials.side_effect = error

    result, _, _, _ = await _submit_credentials(hass, api)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": flow_error}
    assert ACCESS_SECRET not in repr(result.get("description_placeholders"))
    assert ACCESS_SECRET not in caplog.text
    assert "raw secret detail" not in repr(result)
    assert "raw secret detail" not in caplog.text


@pytest.mark.parametrize(
    ("error", "flow_error"),
    [
        (TuyaAuthenticationError("raw secret detail"), "invalid_auth"),
        (
            TuyaAuthorizationError("raw secret detail"),
            "service_not_authorized",
        ),
        (TuyaRateLimitError("raw secret detail"), "rate_limited"),
        (TuyaApiError("raw secret detail"), "cannot_connect"),
        (aiohttp.ClientError("raw secret detail"), "cannot_connect"),
    ],
    ids=["authentication", "authorization", "rate-limit", "api", "aiohttp"],
)
async def test_discovery_failure_returns_to_user_with_actionable_safe_error(
    hass, caplog, error: Exception, flow_error: str
) -> None:
    """Discovery failures do not abort or leak the upstream error."""
    api = _api()
    api.async_discover_devices.side_effect = error

    result, _, _, _ = await _submit_credentials(hass, api)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": flow_error}
    assert ACCESS_SECRET not in repr(result.get("description_placeholders"))
    assert ACCESS_SECRET not in caplog.text
    assert "raw secret detail" not in repr(result)
    assert "raw secret detail" not in caplog.text


async def test_no_discovered_locks_aborts(hass) -> None:
    """An account with no supported lock devices gets a specific abort."""
    api = _api()
    api.async_discover_devices.return_value = []

    result, _, _, _ = await _submit_credentials(hass, api)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_disabled_remote_unlock_stays_on_device_form(hass) -> None:
    """A lock without remote unlock cannot create an entry."""
    api = _api()
    api.async_check_remote_unlock.return_value = False
    result, _, _, _ = await _submit_credentials(hass, api)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_DEVICE_ID: DEVICE_ID},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_device"
    assert result["errors"] == {"base": "remote_unlock_disabled"}
    api.async_discover_devices.assert_awaited_once_with()
    api.async_check_remote_unlock.assert_awaited_once_with(DEVICE_ID)


@pytest.mark.parametrize(
    ("error", "flow_error"),
    [
        (
            TuyaAuthorizationError("raw secret detail"),
            "service_not_authorized",
        ),
        (TuyaRateLimitError("raw secret detail"), "rate_limited"),
        (TuyaApiError("raw secret detail"), "cannot_connect"),
        (aiohttp.ClientError("raw secret detail"), "cannot_connect"),
    ],
    ids=["authorization", "rate-limit", "api", "aiohttp"],
)
async def test_remote_unlock_check_failure_stays_on_device_form_with_safe_error(
    hass, caplog, error: Exception, flow_error: str
) -> None:
    """Retryable capability failures stay on selection with a safe error."""
    api = _api()
    api.async_check_remote_unlock.side_effect = error
    result, _, _, _ = await _submit_credentials(hass, api)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_DEVICE_ID: DEVICE_ID},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_device"
    assert result["errors"] == {"base": flow_error}
    assert ACCESS_SECRET not in repr(result.get("description_placeholders"))
    assert ACCESS_SECRET not in caplog.text
    assert "raw secret detail" not in repr(result)
    assert "raw secret detail" not in caplog.text
    api.async_discover_devices.assert_awaited_once_with()


async def test_remote_auth_failure_restarts_with_corrected_credentials(
    hass, caplog
) -> None:
    """Expired selection credentials are discarded and can be replaced."""
    original_api = _api()
    original_api.async_check_remote_unlock.side_effect = TuyaAuthenticationError(
        "raw secret detail"
    )
    selection, _, _, _ = await _submit_credentials(hass, original_api)

    result = await hass.config_entries.flow.async_configure(
        selection["flow_id"],
        user_input={CONF_DEVICE_ID: DEVICE_ID},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}
    assert ACCESS_SECRET not in repr(result.get("description_placeholders"))
    assert ACCESS_SECRET not in repr(result["errors"])
    assert ACCESS_SECRET not in caplog.text
    assert "raw secret detail" not in repr(result)
    assert "raw secret detail" not in caplog.text

    corrected_secret = "corrected-access-secret"
    corrected_credentials = {
        **CREDENTIALS,
        CONF_ACCESS_SECRET: corrected_secret,
    }
    corrected_api = _api()
    corrected_session = Mock(name="corrected_shared_session")
    with (
        patch(
            "custom_components.tuya_smart_lock.config_flow.async_get_clientsession",
            return_value=corrected_session,
        ),
        patch(
            "custom_components.tuya_smart_lock.config_flow.TuyaCloudApi",
            return_value=corrected_api,
        ) as api_class,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=corrected_credentials,
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_device"
    corrected_api.async_validate_credentials.assert_awaited_once_with()
    corrected_api.async_discover_devices.assert_awaited_once_with()
    api_class.assert_called_once_with(
        corrected_session,
        access_id=ACCESS_ID,
        access_secret=corrected_secret,
        region="eu",
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_DEVICE_ID: DEVICE_ID},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ACCESS_SECRET] == corrected_secret
    assert ACCESS_SECRET not in repr(result["data"])
    original_api.async_discover_devices.assert_awaited_once_with()
    original_api.async_check_remote_unlock.assert_awaited_once_with(DEVICE_ID)
    corrected_api.async_check_remote_unlock.assert_awaited_once_with(DEVICE_ID)


async def test_duplicate_device_aborts_as_already_configured(hass) -> None:
    """An existing device aborts before any capability API request."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE_ID,
        data={},
    ).add_to_hass(hass)
    api = _api()
    api.async_check_remote_unlock.side_effect = TuyaApiError(
        "capability check must not be called"
    )
    result, _, _, _ = await _submit_credentials(hass, api)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_DEVICE_ID: DEVICE_ID},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    api.async_check_remote_unlock.assert_not_awaited()


async def test_in_progress_device_claim_blocks_concurrent_capability_check(
    hass,
) -> None:
    """Only the flow that first claims a device may check its capability."""
    first_api = _api()
    second_api = _api()
    capability_started = asyncio.Event()
    release_capability = asyncio.Event()

    async def blocked_capability_check(device_id: str) -> bool:
        assert device_id == DEVICE_ID
        capability_started.set()
        await release_capability.wait()
        return True

    first_api.async_check_remote_unlock.side_effect = blocked_capability_check
    first_flow, _, _, _ = await _submit_credentials(hass, first_api)
    second_flow, _, _, _ = await _submit_credentials(hass, second_api)

    first_selection = asyncio.create_task(
        hass.config_entries.flow.async_configure(
            first_flow["flow_id"],
            user_input={CONF_DEVICE_ID: DEVICE_ID},
        )
    )
    await capability_started.wait()
    try:
        second_result = await hass.config_entries.flow.async_configure(
            second_flow["flow_id"],
            user_input={CONF_DEVICE_ID: DEVICE_ID},
        )
    finally:
        release_capability.set()
        first_result = await first_selection

    assert first_result["type"] is FlowResultType.CREATE_ENTRY
    assert second_result["type"] is FlowResultType.ABORT
    assert second_result["reason"] == "already_in_progress"
    first_api.async_check_remote_unlock.assert_awaited_once_with(DEVICE_ID)
    second_api.async_check_remote_unlock.assert_not_awaited()


def test_english_translation_matches_strings_and_has_actionable_errors() -> None:
    """English setup copy stays synchronized and distinguishes error causes."""
    integration_dir = Path(__file__).parents[1] / "custom_components" / DOMAIN
    strings = json.loads((integration_dir / "strings.json").read_text())
    translation = json.loads((integration_dir / "translations" / "en.json").read_text())

    assert translation == strings
    errors = strings["config"]["error"]
    authorization = errors["service_not_authorized"]
    assert "IoT Core" in authorization
    assert "Smart Lock Open Service" in authorization
    rate_limit = errors["rate_limited"]
    assert "wait" in rate_limit.casefold()
    assert "retry" in rate_limit.casefold()
    assert "credential" not in rate_limit.casefold()
