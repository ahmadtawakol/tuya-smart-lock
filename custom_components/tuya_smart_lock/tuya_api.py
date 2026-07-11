"""Tuya Cloud API client for Smart Lock operations."""

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any

import aiohttp

from .const import (
    API_REGIONS,
    DOOR_OPERATE_ENDPOINT,
    LOCK_CATEGORIES,
    REMOTE_UNLOCKS_ENDPOINT,
    SHADOW_PROPERTIES_ENDPOINT,
    TICKET_ENDPOINT,
)
from .errors import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaCommandError,
    TuyaRateLimitError,
)
from .models import TuyaProperty, properties_by_code

TOKEN_PATH = "/v1.0/token?grant_type=1"
DISCOVERY_PATH = "/v1.0/iot-01/associated-users/devices"
TOKEN_EXPIRY_MARGIN_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 12

AUTHENTICATION_ERROR_CODES = frozenset(
    {"1001", "1002", "1004", "1005", "1007", "1008"}
)
INVALID_TOKEN_ERROR_CODES = frozenset({"1010", "1011", "1012", "1400"})
AUTHORIZATION_ERROR_CODES = frozenset(
    {
        "1106",
        "1114",
        "2406",
        "28841001",
        "28841002",
        "28841003",
        "28841101",
        "28841102",
        "28841103",
        "28841105",
        "28841106",
    }
)
RATE_LIMIT_ERROR_CODES = frozenset(
    {"429", "1110", "1111", "1113", "1199", "28841004", "28841104"}
)

AUTHENTICATION_MESSAGE_MARKERS = (
    "access token",
    "access_token",
    "appkey invalid",
    "clientid invalid",
    "secret invalid",
    "sign invalid",
    "token expired",
    "token invalid",
)
AUTHORIZATION_MESSAGE_MARKERS = (
    "commercial version",
    "no permission",
    "not authorized",
    "permission deny",
    "subscription",
)
RATE_LIMIT_MESSAGE_MARKERS = (
    "concurrent request over limit",
    "rate limit",
    "system is busy",
    "too many request",
)


class TuyaCloudApi:
    """Tuya Cloud API client using Home Assistant's shared session."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        access_id: str,
        access_secret: str,
        region: str = "eu",
    ) -> None:
        """Initialize the cloud client."""
        self._session = session
        self._access_id = access_id
        self._access_secret = access_secret
        self._base_url = f"https://{API_REGIONS[region]}"
        self._token: str | None = None
        self._token_expiry = 0.0

    def _signed_headers(
        self,
        method: str,
        path: str,
        body: str,
        *,
        access_token: str | None,
    ) -> dict[str, str]:
        """Build Tuya HMAC-SHA256 headers for the exact request bytes."""
        timestamp = str(int(time.time() * 1000))
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        string_to_sign = f"{method}\n{content_hash}\n\n{path}"
        sign_input = self._access_id
        if access_token is not None:
            sign_input += access_token
        sign_input += timestamp + string_to_sign
        signature = hmac.new(
            self._access_secret.encode(),
            sign_input.encode(),
            hashlib.sha256,
        ).hexdigest().upper()

        headers = {
            "client_id": self._access_id,
            "sign": signature,
            "t": timestamp,
            "sign_method": "HMAC-SHA256",
            "Content-Type": "application/json",
        }
        if access_token is not None:
            headers["access_token"] = access_token
        return headers

    async def _send(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: str,
    ) -> tuple[Mapping[str, Any], int]:
        """Send one request and return a decoded mapping without leaking failures."""
        network_failed = False
        decode_failed = False
        status = 0
        payload: object = None
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                data=body or None,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as response:
                status = response.status
                payload = await response.json()
        except aiohttp.ContentTypeError:
            decode_failed = True
        except (aiohttp.ClientError, TimeoutError):
            network_failed = True
        except ValueError:
            decode_failed = True

        if network_failed:
            raise TuyaApiError("Unable to communicate with Tuya.")
        if decode_failed:
            if status >= 400:
                return {}, status
            raise TuyaApiError("Tuya API returned an invalid response.")

        if not isinstance(payload, Mapping):
            if status >= 400:
                return {}, status
            raise TuyaApiError("Tuya API returned an invalid response.")
        return payload, status

    @staticmethod
    def _error_code(payload: Mapping[str, Any]) -> str | None:
        """Return a safe normalized Tuya error code."""
        code = payload.get("code")
        if isinstance(code, bool):
            return None
        if isinstance(code, int):
            return str(code)
        if isinstance(code, str) and len(code) <= 20 and code.isdecimal():
            return code
        return None

    @staticmethod
    def _message_matches(message: object, markers: tuple[str, ...]) -> bool:
        """Return whether a Tuya message matches an explicit category marker."""
        if not isinstance(message, str):
            return False
        normalized_message = message.casefold()
        return any(marker in normalized_message for marker in markers)

    def _raise_response_error(
        self,
        payload: Mapping[str, Any],
        *,
        status: int,
        token_request: bool = False,
        command_request: bool = False,
    ) -> None:
        """Raise a typed error while discarding the raw Tuya response message."""
        code = self._error_code(payload)
        message = payload.get("msg")

        if status == 429:
            raise TuyaRateLimitError(
                "Tuya API rate limit exceeded.",
                code=code,
            )
        if status == 401:
            raise TuyaAuthenticationError(
                "Tuya authentication failed.",
                code=code,
            )
        if status == 403:
            raise TuyaAuthorizationError(
                "Tuya API access is not authorized.",
                code=code,
            )
        if code in RATE_LIMIT_ERROR_CODES or self._message_matches(
            message, RATE_LIMIT_MESSAGE_MARKERS
        ):
            raise TuyaRateLimitError(
                "Tuya API rate limit exceeded.",
                code=code,
            )
        if (
            token_request
            or code in AUTHENTICATION_ERROR_CODES
            or code in INVALID_TOKEN_ERROR_CODES
            or self._message_matches(message, AUTHENTICATION_MESSAGE_MARKERS)
        ):
            raise TuyaAuthenticationError(
                "Tuya authentication failed.",
                code=code,
            )
        if code in AUTHORIZATION_ERROR_CODES or self._message_matches(
            message, AUTHORIZATION_MESSAGE_MARKERS
        ):
            raise TuyaAuthorizationError(
                "Tuya API access is not authorized.",
                code=code,
            )
        if command_request:
            raise TuyaCommandError(
                "Tuya lock command failed.",
                code=code,
            )
        raise TuyaApiError("Tuya API request failed.", code=code)

    async def _ensure_token(self) -> None:
        """Get or refresh the cached access token."""
        if self._token is not None and time.time() < self._token_expiry:
            return

        headers = self._signed_headers(
            "GET",
            TOKEN_PATH,
            "",
            access_token=None,
        )
        payload, status = await self._send(
            "GET",
            TOKEN_PATH,
            headers=headers,
            body="",
        )
        if status >= 400 or payload.get("success") is not True:
            self._raise_response_error(payload, status=status, token_request=True)

        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise TuyaAuthenticationError("Tuya authentication failed.")
        access_token = result.get("access_token")
        expire_time = result.get("expire_time")
        if (
            not isinstance(access_token, str)
            or not access_token
            or isinstance(expire_time, bool)
            or not isinstance(expire_time, (int, float))
            or expire_time <= 0
        ):
            raise TuyaAuthenticationError("Tuya authentication failed.")

        self._token = access_token
        lifetime = max(expire_time - TOKEN_EXPIRY_MARGIN_SECONDS, 0)
        self._token_expiry = time.time() + lifetime

    async def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        command_request: bool = False,
    ) -> Mapping[str, Any]:
        """Make one authenticated Tuya API request."""
        body_string = (
            json.dumps(body, separators=(",", ":")) if body is not None else ""
        )
        for attempt in range(2):
            await self._ensure_token()
            if self._token is None:
                raise TuyaAuthenticationError("Tuya authentication failed.")

            headers = self._signed_headers(
                method,
                path,
                body_string,
                access_token=self._token,
            )
            payload, status = await self._send(
                method,
                path,
                headers=headers,
                body=body_string,
            )
            if status < 400 and payload.get("success") is True:
                return payload
            invalid_token = (
                status == 401
                or self._error_code(payload) in INVALID_TOKEN_ERROR_CODES
            )
            if invalid_token:
                self._token = None
                self._token_expiry = 0
                if attempt == 0:
                    continue
            self._raise_response_error(
                payload,
                status=status,
                command_request=command_request,
            )

        raise TuyaApiError("Tuya API request failed.")

    async def async_validate_credentials(self) -> None:
        """Validate credentials by acquiring or reusing an access token."""
        await self._ensure_token()

    async def async_discover_devices(self) -> list[dict[str, str]]:
        """Discover supported lock devices linked to this account."""
        response = await self._request("GET", DISCOVERY_PATH)
        result = response.get("result")
        if isinstance(result, Mapping):
            records = result.get("devices")
        else:
            records = result
        if not isinstance(records, list):
            return []

        devices: list[dict[str, str]] = []
        for record in records:
            if not isinstance(record, Mapping):
                continue
            device_id = record.get("id")
            category = record.get("category")
            if (
                not isinstance(device_id, str)
                or not device_id
                or not isinstance(category, str)
                or category not in LOCK_CATEGORIES
            ):
                continue
            name = record.get("name")
            model = record.get("model")
            product_name = record.get("product_name")
            devices.append(
                {
                    "id": device_id,
                    "name": name if isinstance(name, str) and name else device_id,
                    "category": category,
                    "model": model if isinstance(model, str) else "",
                    "product_name": (
                        product_name if isinstance(product_name, str) else ""
                    ),
                }
            )
        return devices

    async def async_check_remote_unlock(self, device_id: str) -> bool:
        """Check if remote unlock without a password is enabled."""
        path = REMOTE_UNLOCKS_ENDPOINT.format(device_id=device_id)
        response = await self._request("GET", path)
        result = response.get("result")
        if not isinstance(result, list):
            return False
        for unlock_type in result:
            if (
                isinstance(unlock_type, Mapping)
                and unlock_type.get("remote_unlock_type")
                == "remoteUnlockWithoutPwd"
            ):
                return unlock_type.get("open") is True
        return False

    async def async_get_properties(
        self,
        device_id: str,
    ) -> dict[str, TuyaProperty]:
        """Return normalized device shadow properties keyed by code."""
        path = SHADOW_PROPERTIES_ENDPOINT.format(device_id=device_id)
        response = await self._request("GET", path)
        return properties_by_code(response)

    async def async_operate_lock(self, device_id: str, *, open_: bool) -> None:
        """Lock or unlock a device using Tuya's password-ticket flow."""
        ticket_path = TICKET_ENDPOINT.format(device_id=device_id)
        ticket_response = await self._request(
            "POST",
            ticket_path,
            command_request=True,
        )
        ticket_result = ticket_response.get("result")
        if not isinstance(ticket_result, Mapping):
            raise TuyaCommandError("Tuya lock command failed.")
        ticket_id = ticket_result.get("ticket_id")
        if not isinstance(ticket_id, str) or not ticket_id:
            raise TuyaCommandError("Tuya lock command failed.")

        operate_path = DOOR_OPERATE_ENDPOINT.format(device_id=device_id)
        operate_response = await self._request(
            "POST",
            operate_path,
            {"ticket_id": ticket_id, "open": open_},
            command_request=True,
        )
        if operate_response.get("result") is not True:
            raise TuyaCommandError("Tuya lock command failed.")
