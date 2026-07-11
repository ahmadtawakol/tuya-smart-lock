"""Tests for the shared-session Tuya Cloud API client."""

import hashlib
import hmac
import logging
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.tuya_smart_lock import tuya_api as tuya_api_module
from custom_components.tuya_smart_lock.errors import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaCommandError,
    TuyaRateLimitError,
)
from custom_components.tuya_smart_lock.models import TuyaProperty
from custom_components.tuya_smart_lock.tuya_api import TuyaCloudApi

ACCESS_ID = "test-access-id"
ACCESS_SECRET = "test-access-secret"
ACCESS_TOKEN = "test-access-token"
BASE_URL = "https://openapi.tuyaeu.com"
TOKEN_PATH = "/v1.0/token?grant_type=1"
TOKEN_URL = f"{BASE_URL}{TOKEN_PATH}"
DEVICE_ID = "videolock-device"
FIXED_TIME = 1_700_000_000.123
FIXED_TIMESTAMP = "1700000000123"

SUPPORTED_CODE_CASES = [
    *(
        (code, TuyaAuthenticationError, "Tuya authentication failed.")
        for code in (1001, 1002, 1004, 1005, 1007, 1008, 1010, 1011, 1012, 1400)
    ),
    *(
        (code, TuyaAuthorizationError, "Tuya API access is not authorized.")
        for code in (
            1106,
            2406,
            28841001,
            28841002,
            28841101,
            28841102,
            28841105,
            28841106,
        )
    ),
    *(
        (code, TuyaRateLimitError, "Tuya API rate limit exceeded.")
        for code in (429, 1110, 1111, 1113, 1199, 28841004, 28841104)
    ),
]


def _register_token(
    aioclient_mock: AiohttpClientMocker,
    *,
    expire_time: int = 7200,
) -> None:
    """Register a successful Tuya token response."""
    aioclient_mock.get(
        TOKEN_URL,
        json={
            "success": True,
            "result": {
                "access_token": ACCESS_TOKEN,
                "expire_time": expire_time,
                "uid": "test-user",
            },
        },
    )


def _api(hass: HomeAssistant) -> TuyaCloudApi:
    """Build an API client with Home Assistant's shared session."""
    return TuyaCloudApi(
        async_get_clientsession(hass),
        ACCESS_ID,
        ACCESS_SECRET,
    )


def _expected_sign(*, path: str, body: str = "", token: str = "") -> str:
    """Return the signature expected for a request at the frozen time."""
    content_hash = hashlib.sha256(body.encode()).hexdigest()
    string_to_sign = f"GET\n{content_hash}\n\n{path}"
    sign_input = f"{ACCESS_ID}{token}{FIXED_TIMESTAMP}{string_to_sign}"
    return hmac.new(
        ACCESS_SECRET.encode(),
        sign_input.encode(),
        hashlib.sha256,
    ).hexdigest().upper()


async def test_token_request_uses_expected_signature_and_safe_headers(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token signing omits both the token and access secret from headers."""
    monkeypatch.setattr(
        "custom_components.tuya_smart_lock.tuya_api.time.time",
        lambda: FIXED_TIME,
    )
    _register_token(aioclient_mock)

    await _api(hass).async_validate_credentials()

    method, url, body, headers = aioclient_mock.mock_calls[0]
    assert method == "GET"
    assert str(url) == TOKEN_URL
    assert body is None
    assert headers["client_id"] == ACCESS_ID
    assert headers["t"] == FIXED_TIMESTAMP
    assert headers["sign_method"] == "HMAC-SHA256"
    assert headers["sign"] == _expected_sign(path=TOKEN_PATH)
    assert "access_token" not in headers
    assert "secret" not in headers


async def test_unexpired_token_is_reused(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated credential validation reuses an unexpired token."""
    monkeypatch.setattr(
        "custom_components.tuya_smart_lock.tuya_api.time.time",
        lambda: FIXED_TIME,
    )
    _register_token(aioclient_mock)
    api = _api(hass)

    await api.async_validate_credentials()
    await api.async_validate_credentials()

    assert aioclient_mock.call_count == 1


async def test_expired_token_is_refreshed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token is requested again after its safety-adjusted expiry."""
    now = [FIXED_TIME]
    monkeypatch.setattr(
        "custom_components.tuya_smart_lock.tuya_api.time.time",
        lambda: now[0],
    )
    _register_token(aioclient_mock, expire_time=120)
    api = _api(hass)

    await api.async_validate_credentials()
    now[0] += 61
    await api.async_validate_credentials()

    assert aioclient_mock.call_count == 2


async def test_rejected_cached_token_is_refreshed_and_request_retried_once(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A server-rejected cached token is replaced before one business retry."""
    fresh_token = "fresh-access-token"
    issued_tokens = iter((ACCESS_TOKEN, fresh_token))

    async def token_response(method, url, data):
        return AiohttpClientMockResponse(
            method,
            url,
            json={
                "success": True,
                "result": {
                    "access_token": next(issued_tokens),
                    "expire_time": 7200,
                },
            },
        )

    business_responses = iter(
        (
            {"success": False, "code": 1010, "msg": "token expired"},
            {"success": True, "result": {"properties": []}},
        )
    )

    async def business_response(method, url, data):
        return AiohttpClientMockResponse(
            method,
            url,
            json=next(business_responses),
        )

    aioclient_mock.get(TOKEN_URL, side_effect=token_response)
    properties_url = (
        f"{BASE_URL}/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties"
    )
    aioclient_mock.get(properties_url, side_effect=business_response)
    api = _api(hass)
    await api.async_validate_credentials()

    assert await api.async_get_properties(DEVICE_ID) == {}

    assert aioclient_mock.call_count == 4
    business_calls = [
        call for call in aioclient_mock.mock_calls if str(call[1]) == properties_url
    ]
    assert [call[3]["access_token"] for call in business_calls] == [
        ACCESS_TOKEN,
        fresh_token,
    ]


async def test_rejected_token_retry_is_bounded_to_one_attempt(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A second invalid-token response is raised instead of retried again."""
    issued_tokens = iter((ACCESS_TOKEN, "fresh-access-token"))

    async def token_response(method, url, data):
        return AiohttpClientMockResponse(
            method,
            url,
            json={
                "success": True,
                "result": {
                    "access_token": next(issued_tokens),
                    "expire_time": 7200,
                },
            },
        )

    aioclient_mock.get(TOKEN_URL, side_effect=token_response)
    properties_url = (
        f"{BASE_URL}/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties"
    )
    aioclient_mock.get(
        properties_url,
        json={
            "success": False,
            "code": 1011,
            "msg": (
                f"token invalid {ACCESS_TOKEN} fresh-access-token ticket-material"
            ),
        },
    )
    api = _api(hass)
    await api.async_validate_credentials()

    with caplog.at_level(logging.DEBUG), pytest.raises(
        TuyaAuthenticationError
    ) as error:
        await api.async_get_properties(DEVICE_ID)

    assert error.value.code == "1011"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert aioclient_mock.call_count == 4
    assert sum(
        str(call[1]) == properties_url for call in aioclient_mock.mock_calls
    ) == 2
    exposed = f"{error.value}\n{caplog.text}"
    for sensitive in (ACCESS_TOKEN, "fresh-access-token", "ticket-material"):
        assert sensitive not in exposed


async def test_client_uses_injected_session_without_constructing_one(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """All traffic goes through the Home Assistant-owned client session."""
    _register_token(aioclient_mock)
    api = _api(hass)

    with patch(
        "custom_components.tuya_smart_lock.tuya_api.aiohttp.ClientSession",
        side_effect=AssertionError("must use injected session"),
    ) as client_session:
        await api.async_validate_credentials()

    client_session.assert_not_called()
    assert aioclient_mock.call_count == 1


async def test_every_request_uses_named_bounded_timeout(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Token and authenticated requests use the same bounded request timeout."""
    _register_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties",
        json={"success": True, "result": {"properties": []}},
    )
    session = async_get_clientsession(hass)
    api = TuyaCloudApi(session, ACCESS_ID, ACCESS_SECRET)

    with patch.object(session, "request", wraps=session.request) as request:
        await api.async_get_properties(DEVICE_ID)

    assert request.call_count == 2
    timeouts = [call.kwargs.get("timeout") for call in request.call_args_list]
    assert all(isinstance(timeout, aiohttp.ClientTimeout) for timeout in timeouts)
    assert [timeout.total for timeout in timeouts] == [12, 12]
    assert getattr(tuya_api_module, "REQUEST_TIMEOUT_SECONDS", None) == 12


@pytest.mark.parametrize("exception_type", [TimeoutError, aiohttp.ServerTimeoutError])
async def test_timeout_exception_is_sanitized_without_chained_leakage(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
    exception_type: type[BaseException],
) -> None:
    """Asyncio and aiohttp timeouts expose only the fixed public API error."""
    raw_marker = f"timeout {ACCESS_SECRET} {ACCESS_TOKEN} ticket-material"
    aioclient_mock.get(TOKEN_URL, exc=exception_type(raw_marker))

    with caplog.at_level(logging.DEBUG), pytest.raises(TuyaApiError) as error:
        await _api(hass).async_validate_credentials()

    exposed = f"{error.value}\n{caplog.text}"
    assert str(error.value) == "Unable to communicate with Tuya."
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    for sensitive in (ACCESS_SECRET, ACCESS_TOKEN, "ticket-material"):
        assert sensitive not in exposed


async def test_token_failure_is_sanitized(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Credential failures never expose Tuya response or credential material."""
    raw_marker = "raw-response-marker"
    aioclient_mock.get(
        TOKEN_URL,
        json={
            "success": False,
            "code": 1004,
            "msg": (
                f"{raw_marker} {ACCESS_SECRET} {ACCESS_TOKEN} ticket-material"
            ),
        },
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(
        TuyaAuthenticationError
    ) as error:
        await _api(hass).async_validate_credentials()

    exposed = f"{error.value}\n{caplog.text}"
    assert error.value.code == "1004"
    assert str(error.value) == "Tuya authentication failed."
    for sensitive in (
        ACCESS_SECRET,
        ACCESS_TOKEN,
        "ticket-material",
        raw_marker,
    ):
        assert sensitive not in exposed


async def test_token_rate_limit_raises_rate_limit_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Rate limiting remains distinct from ordinary token rejection."""
    aioclient_mock.get(
        TOKEN_URL,
        status=429,
        json={"success": False, "code": 429, "msg": "Too many requests"},
    )

    with pytest.raises(TuyaRateLimitError) as error:
        await _api(hass).async_validate_credentials()

    assert str(error.value) == "Tuya API rate limit exceeded."
    assert error.value.code == "429"


async def test_get_properties_uses_shadow_endpoint_and_normalizes_result(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Shadow properties are returned as Task 1's normalized mapping."""
    _register_token(aioclient_mock)
    path = f"/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties"
    aioclient_mock.get(
        f"{BASE_URL}{path}",
        json={
            "success": True,
            "result": {
                "properties": [
                    {
                        "code": "doorbell",
                        "dp_id": 53,
                        "time": 1_783_792_375,
                        "value": True,
                    }
                ]
            },
        },
    )

    result = await _api(hass).async_get_properties(DEVICE_ID)

    assert result == {
        "doorbell": TuyaProperty(
            code="doorbell",
            value=True,
            timestamp_ms=1_783_792_375_000,
            dp_id=53,
        )
    }
    assert str(aioclient_mock.mock_calls[1][1]) == f"{BASE_URL}{path}"


async def test_get_properties_handles_malformed_payload(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Malformed successful property payloads safely produce an empty mapping."""
    _register_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties",
        json={"success": True, "result": {"properties": "not-a-list"}},
    )

    assert await _api(hass).async_get_properties(DEVICE_ID) == {}


@pytest.mark.parametrize("open_", [False, True])
async def test_operate_lock_uses_ticket_and_exact_compact_body(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
    open_: bool,
) -> None:
    """Lock and unlock operations transmit the ticket in the signed body."""
    monkeypatch.setattr(
        "custom_components.tuya_smart_lock.tuya_api.time.time",
        lambda: FIXED_TIME,
    )
    _register_token(aioclient_mock)
    ticket_path = f"/v1.0/devices/{DEVICE_ID}/door-lock/password-ticket"
    operate_path = (
        f"/v1.0/smart-lock/devices/{DEVICE_ID}/password-free/door-operate"
    )
    aioclient_mock.post(
        f"{BASE_URL}{ticket_path}",
        json={"success": True, "result": {"ticket_id": "ticket"}},
    )
    aioclient_mock.post(
        f"{BASE_URL}{operate_path}",
        json={"success": True, "result": True},
    )

    await _api(hass).async_operate_lock(DEVICE_ID, open_=open_)

    ticket_call = aioclient_mock.mock_calls[1]
    operate_call = aioclient_mock.mock_calls[2]
    body = f'{{"ticket_id":"ticket","open":{str(open_).lower()}}}'
    assert ticket_call[0] == "POST"
    assert str(ticket_call[1]) == f"{BASE_URL}{ticket_path}"
    assert ticket_call[2] is None
    assert operate_call[0] == "POST"
    assert str(operate_call[1]) == f"{BASE_URL}{operate_path}"
    assert operate_call[2] == body

    content_hash = hashlib.sha256(body.encode()).hexdigest()
    string_to_sign = f"POST\n{content_hash}\n\n{operate_path}"
    sign_input = (
        f"{ACCESS_ID}{ACCESS_TOKEN}{FIXED_TIMESTAMP}{string_to_sign}"
    )
    expected_sign = hmac.new(
        ACCESS_SECRET.encode(),
        sign_input.encode(),
        hashlib.sha256,
    ).hexdigest().upper()
    assert operate_call[3]["sign"] == expected_sign
    assert operate_call[3]["access_token"] == ACCESS_TOKEN


async def test_missing_ticket_id_raises_command_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A successful ticket response without a ticket is a command failure."""
    _register_token(aioclient_mock)
    aioclient_mock.post(
        f"{BASE_URL}/v1.0/devices/{DEVICE_ID}/door-lock/password-ticket",
        json={"success": True, "result": {}},
    )

    with pytest.raises(TuyaCommandError, match="Tuya lock command failed"):
        await _api(hass).async_operate_lock(DEVICE_ID, open_=True)


async def test_command_rejection_raises_sanitized_command_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Door-operation rejection is typed and excludes all sensitive material."""
    property_value = "private-property-value"
    raw_marker = "raw-command-response"
    _register_token(aioclient_mock)
    aioclient_mock.post(
        f"{BASE_URL}/v1.0/devices/{DEVICE_ID}/door-lock/password-ticket",
        json={"success": True, "result": {"ticket_id": "ticket-material"}},
    )
    aioclient_mock.post(
        (
            f"{BASE_URL}/v1.0/smart-lock/devices/{DEVICE_ID}"
            "/password-free/door-operate"
        ),
        json={
            "success": False,
            "code": 1103,
            "msg": (
                f"{raw_marker} {ACCESS_SECRET} {ACCESS_TOKEN} "
                f"ticket-material {property_value}"
            ),
        },
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(TuyaCommandError) as error:
        await _api(hass).async_operate_lock(DEVICE_ID, open_=False)

    exposed = f"{error.value}\n{caplog.text}"
    assert error.value.code == "1103"
    assert str(error.value) == "Tuya lock command failed."
    for sensitive in (
        ACCESS_SECRET,
        ACCESS_TOKEN,
        "ticket-material",
        property_value,
        raw_marker,
    ):
        assert sensitive not in exposed


@pytest.mark.parametrize(
    ("response", "error_type", "message", "code"),
    [
        (
            {"success": False, "code": 1011, "msg": "token invalid"},
            TuyaAuthenticationError,
            "Tuya authentication failed.",
            "1011",
        ),
        (
            {"success": False, "code": 1106, "msg": "permission deny"},
            TuyaAuthorizationError,
            "Tuya API access is not authorized.",
            "1106",
        ),
        (
            {
                "success": False,
                "code": "unknown",
                "msg": "Subscription is not active",
            },
            TuyaAuthorizationError,
            "Tuya API access is not authorized.",
            None,
        ),
        (
            {
                "success": False,
                "code": "unknown",
                "msg": "Too many requests",
            },
            TuyaRateLimitError,
            "Tuya API rate limit exceeded.",
            None,
        ),
    ],
)
async def test_unsuccessful_responses_raise_typed_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    response: dict[str, object],
    error_type: type[TuyaApiError],
    message: str,
    code: str | None,
) -> None:
    """Representative Tuya codes and messages map to fixed public errors."""
    _register_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties",
        json=response,
    )

    with pytest.raises(error_type) as error:
        await _api(hass).async_get_properties(DEVICE_ID)

    assert str(error.value) == message
    assert error.value.code == code


@pytest.mark.parametrize(("code", "error_type", "message"), SUPPORTED_CODE_CASES)
async def test_supported_error_codes_are_authoritatively_classified(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    code: int,
    error_type: type[TuyaApiError],
    message: str,
) -> None:
    """Every explicitly supported Tuya code maps to its public error category."""
    _register_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties",
        json={"success": False, "code": code, "msg": "opaque"},
    )

    with pytest.raises(error_type) as error:
        await _api(hass).async_get_properties(DEVICE_ID)

    assert str(error.value) == message
    assert error.value.code == str(code)


async def test_other_unsuccessful_response_raises_api_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Unclassified cloud failures use the safe base API error."""
    _register_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties",
        json={"success": False, "code": 500, "msg": "internal details"},
    )

    with pytest.raises(TuyaApiError) as error:
        await _api(hass).async_get_properties(DEVICE_ID)

    assert type(error.value) is TuyaApiError
    assert str(error.value) == "Tuya API request failed."
    assert error.value.code == "500"


async def test_non_numeric_error_code_is_not_exposed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Only expected numeric Tuya codes are retained on public errors."""
    _register_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties",
        json={
            "success": False,
            "code": ACCESS_SECRET,
            "msg": "Too many requests",
        },
    )

    with pytest.raises(TuyaRateLimitError) as error:
        await _api(hass).async_get_properties(DEVICE_ID)

    assert error.value.code is None
    assert ACCESS_SECRET not in str(error.value)


async def test_client_exception_raises_sanitized_api_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Network errors are converted without exposing their original text."""
    raw_marker = f"network {ACCESS_SECRET} {ACCESS_TOKEN} ticket-material"
    _register_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties",
        exc=aiohttp.ClientError(raw_marker),
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(TuyaApiError) as error:
        await _api(hass).async_get_properties(DEVICE_ID)

    exposed = f"{error.value}\n{caplog.text}"
    assert str(error.value) == "Unable to communicate with Tuya."
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    for sensitive in (ACCESS_SECRET, ACCESS_TOKEN, "ticket-material"):
        assert sensitive not in exposed


async def test_invalid_json_response_body_is_sanitized(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A malformed raw response body is never exposed to callers or logs."""
    raw_body = f"not-json {ACCESS_SECRET} {ACCESS_TOKEN} ticket-material"
    _register_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties",
        text=raw_body,
        headers={"Content-Type": "application/json"},
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(TuyaApiError) as error:
        await _api(hass).async_get_properties(DEVICE_ID)

    exposed = f"{error.value}\n{caplog.text}"
    assert str(error.value) == "Tuya API returned an invalid response."
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    for sensitive in (ACCESS_SECRET, ACCESS_TOKEN, "ticket-material"):
        assert sensitive not in exposed


@pytest.mark.parametrize(
    ("status", "error_type", "message"),
    [
        (401, TuyaAuthenticationError, "Tuya authentication failed."),
        (403, TuyaAuthorizationError, "Tuya API access is not authorized."),
        (429, TuyaRateLimitError, "Tuya API rate limit exceeded."),
        (200, TuyaApiError, "Tuya API returned an invalid response."),
    ],
)
async def test_non_json_response_preserves_http_error_classification(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
    status: int,
    error_type: type[TuyaApiError],
    message: str,
) -> None:
    """Malformed bodies retain safe HTTP 401, 403, and 429 classification."""
    raw_body = f"not-json {ACCESS_SECRET} {ACCESS_TOKEN} ticket-material"
    _register_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties",
        status=status,
        text=raw_body,
        headers={"Content-Type": "application/json"},
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(error_type) as error:
        await _api(hass).async_get_properties(DEVICE_ID)

    exposed = f"{error.value}\n{caplog.text}"
    assert str(error.value) == message
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    for sensitive in (ACCESS_SECRET, ACCESS_TOKEN, "ticket-material"):
        assert sensitive not in exposed


async def test_discovery_filters_to_supported_lock_categories(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Discovery preserves the existing supported lock-category filter."""
    _register_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v1.0/iot-01/associated-users/devices",
        json={
            "success": True,
            "result": {
                "devices": [
                    {
                        "id": DEVICE_ID,
                        "name": "Front Door",
                        "category": "videolock",
                        "model": "VL-1",
                        "product_name": "Video Lock",
                    },
                    {
                        "id": "light-device",
                        "name": "Hall Light",
                        "category": "dj",
                    },
                ]
            },
        },
    )

    assert await _api(hass).async_discover_devices() == [
        {
            "id": DEVICE_ID,
            "name": "Front Door",
            "category": "videolock",
            "model": "VL-1",
            "product_name": "Video Lock",
        }
    ]


async def test_check_remote_unlock_reads_password_free_capability(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Remote-unlock capability is read from the existing Tuya endpoint."""
    _register_token(aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/v1.0/devices/{DEVICE_ID}/door-lock/remote-unlocks",
        json={
            "success": True,
            "result": [
                {
                    "remote_unlock_type": "remoteUnlockWithoutPwd",
                    "open": True,
                }
            ],
        },
    )

    assert await _api(hass).async_check_remote_unlock(DEVICE_ID) is True
