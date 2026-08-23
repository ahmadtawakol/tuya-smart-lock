"""Tests for Tuya Smart Lock setup through the official Tuya integration."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_platform

from custom_components.tuya_smart_lock import config_flow
from custom_components.tuya_smart_lock.const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_API_REGION,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_TUYA_ENTRY_ID,
    DOMAIN,
)
from custom_components.tuya_smart_lock.errors import (
    TuyaApiError,
    TuyaAuthenticationError,
)

ACCESS_ID = "legacy-access-id"
ACCESS_SECRET = "legacy-sensitive-secret"
DEVICE_ID = "lock-123"
DEVICE_NAME = "Front Door"
OFFICIAL_ENTRY_ID = "official-tuya-entry"
LEGACY_CREDENTIALS = {
    CONF_ACCESS_ID: ACCESS_ID,
    CONF_ACCESS_SECRET: ACCESS_SECRET,
    CONF_API_REGION: "eu",
}


def _device(
    *,
    device_id: str = DEVICE_ID,
    name: str = DEVICE_NAME,
    category: str = "videolock",
):
    """Return a minimal official Tuya device."""
    return SimpleNamespace(id=device_id, name=name, category=category)


def _official_entry(devices, *, loaded: bool = True) -> MockConfigEntry:
    """Return an official Tuya entry with a Device Sharing manager."""
    entry = MockConfigEntry(
        domain="tuya",
        entry_id=OFFICIAL_ENTRY_ID,
        title="Smart Life account",
        data={},
        state=(ConfigEntryState.LOADED if loaded else ConfigEntryState.NOT_LOADED),
    )
    if loaded:
        entry.runtime_data = SimpleNamespace(
            manager=SimpleNamespace(
                device_map={device.id: device for device in devices}
            )
        )
    return entry


def _legacy_entry() -> MockConfigEntry:
    """Return an existing v1.1 cloud-credential entry for reauthentication."""
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="legacy-entry",
        unique_id=DEVICE_ID,
        title=DEVICE_NAME,
        data={
            **LEGACY_CREDENTIALS,
            CONF_DEVICE_ID: DEVICE_ID,
            CONF_DEVICE_NAME: DEVICE_NAME,
        },
    )


async def _start_flow(hass, official_entries=None):
    """Start the custom integration's user flow."""
    mock_platform(
        hass,
        f"{DOMAIN}.config_flow",
        config_flow,
        built_in=False,
    )
    with patch.object(
        hass.config_entries,
        "async_entries",
        return_value=official_entries or [],
    ):
        return await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )


async def _start_reauth_flow(hass, entry: MockConfigEntry):
    """Start reauthentication for a legacy entry."""
    mock_platform(
        hass,
        f"{DOMAIN}.config_flow",
        config_flow,
        built_in=False,
    )
    entry.add_to_hass(hass)
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
        data=dict(entry.data),
    )


async def _start_reconfigure_flow(hass, entry, official_entries):
    """Start migration of a legacy entry to free Device Sharing."""
    mock_platform(
        hass,
        f"{DOMAIN}.config_flow",
        config_flow,
        built_in=False,
    )
    entry.add_to_hass(hass)
    with patch.object(
        hass.config_entries,
        "async_entries",
        return_value=official_entries,
    ):
        return await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": entry.entry_id},
            data=dict(entry.data),
        )


async def test_user_flow_requires_loaded_official_tuya(hass) -> None:
    """Setup explains that the free official Tuya login must exist first."""
    result = await _start_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "tuya_not_configured"


async def test_unloaded_official_tuya_is_not_used(hass) -> None:
    """A stale official entry cannot be mistaken for a usable session."""
    entry = _official_entry([_device()], loaded=False)

    result = await _start_flow(hass, [entry])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "tuya_not_configured"


async def test_user_flow_lists_only_supported_lock_categories(hass) -> None:
    """The free setup discovers locks from the official Device Sharing cache."""
    entry = _official_entry(
        [
            _device(),
            _device(device_id="socket-1", name="Socket", category="cz"),
        ],
    )

    result = await _start_flow(hass, [entry])

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_device"
    assert result["errors"] == {}
    selection = f"{OFFICIAL_ENTRY_ID}:{DEVICE_ID}"
    assert result["data_schema"]({CONF_DEVICE_ID: selection}) == {
        CONF_DEVICE_ID: selection
    }
    with pytest.raises(vol.Invalid):
        result["data_schema"]({CONF_DEVICE_ID: f"{OFFICIAL_ENTRY_ID}:socket-1"})


async def test_no_shared_locks_aborts(hass) -> None:
    """A loaded account without supported lock categories is actionable."""
    entry = _official_entry([_device(category="cz")])

    result = await _start_flow(hass, [entry])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_selected_lock_stores_no_developer_credentials(hass) -> None:
    """New entries reference the free official session and contain no secrets."""
    entry = _official_entry([_device()])
    form = await _start_flow(hass, [entry])

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={CONF_DEVICE_ID: f"{OFFICIAL_ENTRY_ID}:{DEVICE_ID}"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == DEVICE_NAME
    assert result["data"] == {
        CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID,
        CONF_DEVICE_ID: DEVICE_ID,
        CONF_DEVICE_NAME: DEVICE_NAME,
    }
    assert result["result"].unique_id == DEVICE_ID
    assert CONF_ACCESS_ID not in result["data"]
    assert CONF_ACCESS_SECRET not in result["data"]


async def test_duplicate_shared_lock_aborts(hass) -> None:
    """One physical lock cannot be claimed by two custom entries."""
    entry = _official_entry([_device()])
    existing = MockConfigEntry(domain=DOMAIN, unique_id=DEVICE_ID, data={})
    existing.add_to_hass(hass)
    form = await _start_flow(hass, [entry])

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={CONF_DEVICE_ID: f"{OFFICIAL_ENTRY_ID}:{DEVICE_ID}"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_legacy_entry_reconfigures_to_free_matching_lock(hass) -> None:
    """Existing users can remove developer secrets without deleting entities."""
    legacy = _legacy_entry()
    official = _official_entry([_device()])
    form = await _start_reconfigure_flow(hass, legacy, [official])

    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "reconfigure_confirm"
    assert form["description_placeholders"] == {"name": DEVICE_NAME}
    with patch.object(
        hass.config_entries,
        "async_schedule_reload",
    ) as reload_entry:
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], user_input={}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert dict(legacy.data) == {
        CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID,
        CONF_DEVICE_ID: DEVICE_ID,
        CONF_DEVICE_NAME: DEVICE_NAME,
    }
    assert legacy.unique_id == DEVICE_ID
    reload_entry.assert_called_once_with(legacy.entry_id)


async def test_reconfigure_requires_same_lock_in_official_tuya(hass) -> None:
    """Migration cannot silently retarget stable entities to another lock."""
    legacy = _legacy_entry()
    official = _official_entry([_device(device_id="another-lock")])

    result = await _start_reconfigure_flow(hass, legacy, [official])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "migration_device_not_found"


async def test_reconfigure_relinks_replaced_official_tuya_entry(hass) -> None:
    """Removing and re-adding official Tuya can repair the stored entry link."""
    sharing = MockConfigEntry(
        domain=DOMAIN,
        entry_id="sharing-entry",
        unique_id=DEVICE_ID,
        title=DEVICE_NAME,
        data={
            CONF_TUYA_ENTRY_ID: "removed-official-entry",
            CONF_DEVICE_ID: DEVICE_ID,
            CONF_DEVICE_NAME: DEVICE_NAME,
        },
    )
    replacement = _official_entry([_device()])

    form = await _start_reconfigure_flow(hass, sharing, [replacement])
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], user_input={}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert sharing.data[CONF_TUYA_ENTRY_ID] == OFFICIAL_ENTRY_ID


async def test_legacy_reauth_still_accepts_replacement_cloud_credentials(hass) -> None:
    """Existing v1.1 entries remain recoverable until users migrate voluntarily."""
    entry = _legacy_entry()
    api = Mock(name="legacy_api")
    api.async_validate_credentials = AsyncMock()
    form = await _start_reauth_flow(hass, entry)
    replacement = {
        CONF_ACCESS_ID: "replacement-id",
        CONF_ACCESS_SECRET: "replacement-secret",
        CONF_API_REGION: "us",
    }

    with (
        patch(
            "custom_components.tuya_smart_lock.config_flow.TuyaCloudApi",
            return_value=api,
        ),
        patch.object(hass.config_entries, "async_schedule_reload") as reload_entry,
    ):
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], user_input=replacement
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert dict(entry.data) == {
        **replacement,
        CONF_DEVICE_ID: DEVICE_ID,
        CONF_DEVICE_NAME: DEVICE_NAME,
    }
    api.async_validate_credentials.assert_awaited_once_with()
    reload_entry.assert_called_once_with(entry.entry_id)


@pytest.mark.parametrize(
    ("error", "flow_error"),
    [
        (TuyaAuthenticationError("raw-auth-detail"), "invalid_auth"),
        (TuyaApiError("raw-network-detail"), "cannot_connect"),
    ],
)
async def test_legacy_reauth_failure_is_safe(
    hass, caplog, error: Exception, flow_error: str
) -> None:
    """Legacy failures retain fixed messages without exposing cloud secrets."""
    entry = _legacy_entry()
    api = Mock(name="legacy_api")
    api.async_validate_credentials = AsyncMock(side_effect=error)
    form = await _start_reauth_flow(hass, entry)

    with patch(
        "custom_components.tuya_smart_lock.config_flow.TuyaCloudApi",
        return_value=api,
    ):
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], user_input=LEGACY_CREDENTIALS
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": flow_error}
    assert result["description_placeholders"] == {"name": DEVICE_NAME}
    assert "raw-auth-detail" not in repr(result)
    assert "raw-network-detail" not in repr(result)
    assert ACCESS_SECRET not in caplog.text


def test_english_translation_matches_strings_and_free_setup_messages() -> None:
    """English strings stay synchronized and explain free app authentication."""
    integration = Path(__file__).parents[1] / "custom_components" / DOMAIN
    strings = json.loads((integration / "strings.json").read_text())
    english = json.loads((integration / "translations" / "en.json").read_text())

    assert english == strings
    assert (
        "official Tuya integration" in strings["config"]["abort"]["tuya_not_configured"]
    )
    assert (
        "Access Secret" not in strings["config"]["step"]["select_device"]["description"]
    )
