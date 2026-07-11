"""Tests for the Tuya Smart Lock lock platform."""

import asyncio
from importlib import import_module
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from homeassistant.components.lock import LockState
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_smart_lock import (
    TuyaSmartLockRuntimeData,
)
from custom_components.tuya_smart_lock import (
    async_setup_entry as async_setup_integration,
)
from custom_components.tuya_smart_lock.binary_sensor import (
    TuyaSmartLockHijackBinarySensor,
)
from custom_components.tuya_smart_lock.const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_API_REGION,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    DOMAIN,
)
from custom_components.tuya_smart_lock.coordinator import TuyaSmartLockCoordinator
from custom_components.tuya_smart_lock.errors import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaCommandError,
    TuyaRateLimitError,
)
from custom_components.tuya_smart_lock.lock import (
    TuyaSmartLock,
    async_setup_entry,
)
from custom_components.tuya_smart_lock.models import (
    TuyaProperty,
    properties_by_code,
)
from custom_components.tuya_smart_lock.sensor import TuyaSmartLockBatterySensor

ENTRY_ID = "entry-123"
DEVICE_ID = "device-123"
DEVICE_NAME = "Front Door"
TIMESTAMP_MS = 1_700_000_000_000


def _entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, entry_id=ENTRY_ID)


def _motor_property(
    value: object,
    *,
    timestamp_ms: int = TIMESTAMP_MS,
) -> dict[str, TuyaProperty]:
    return {
        "lock_motor_state": TuyaProperty(
            code="lock_motor_state",
            value=value,
            timestamp_ms=timestamp_ms,
            dp_id=1,
        )
    }


def _coordinator(
    hass,
    api: AsyncMock,
    data: dict[str, TuyaProperty] | None = None,
) -> TuyaSmartLockCoordinator:
    coordinator = TuyaSmartLockCoordinator(hass, api, DEVICE_ID, _entry())
    coordinator.async_set_updated_data(data or {})
    return coordinator


def _entity(
    hass,
    api: AsyncMock,
    data: dict[str, TuyaProperty] | None = None,
) -> TuyaSmartLock:
    entity = TuyaSmartLock(
        _coordinator(hass, api, data),
        device_id=DEVICE_ID,
        device_name=DEVICE_NAME,
    )
    entity.async_write_ha_state = Mock()
    return entity


async def test_setup_reads_typed_runtime_and_adds_one_entity(hass) -> None:
    """Platform setup adds one coordinator-backed lock from runtime data."""
    entry = _entry()
    api = AsyncMock()
    coordinator = _coordinator(hass, api, _motor_property(False))
    hass.data[DOMAIN] = {
        ENTRY_ID: TuyaSmartLockRuntimeData(
            api=api,
            coordinator=coordinator,
            device_id=DEVICE_ID,
            device_name=DEVICE_NAME,
        )
    }
    async_add_entities = Mock()

    await async_setup_entry(hass, entry, async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args.args[0]
    assert len(entities) == 1
    entity = entities[0]
    assert isinstance(entity, TuyaSmartLock)
    assert entity.coordinator is coordinator


async def test_integration_setup_forwards_coordinator_backed_platforms(
    hass,
) -> None:
    """Config-entry setup forwards all implemented coordinator entities."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        data={
            CONF_ACCESS_ID: "access-id",
            CONF_ACCESS_SECRET: "access-secret",
            CONF_API_REGION: "eu",
            CONF_DEVICE_ID: DEVICE_ID,
            CONF_DEVICE_NAME: DEVICE_NAME,
        },
    )
    entry.add_to_hass(hass)
    api = AsyncMock()
    api.async_get_properties.return_value = _motor_property(False)
    entities = []

    async def forward_platforms(forwarded_entry, platforms) -> None:
        assert forwarded_entry is entry
        for platform in platforms:
            module = import_module(
                f"custom_components.tuya_smart_lock.{platform.value}"
            )
            await module.async_setup_entry(hass, entry, entities.extend)

    forward = AsyncMock(side_effect=forward_platforms)
    entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)

    with (
        patch(
            "custom_components.tuya_smart_lock.TuyaCloudApi",
            return_value=api,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=forward,
        ),
    ):
        assert await async_setup_integration(hass, entry) is True

    assert len(entities) == 7
    assert isinstance(entities[0], TuyaSmartLock)
    assert isinstance(entities[1], TuyaSmartLockBatterySensor)
    assert isinstance(entities[2], TuyaSmartLockHijackBinarySensor)
    assert entities[0].state == LockState.LOCKED
    assert entities[1].native_value is None
    assert entities[2].is_on is None
    api.async_get_properties.assert_awaited_once_with(DEVICE_ID)


@pytest.mark.parametrize(
    ("motor_state", "expected_locked", "expected_state"),
    [
        (True, False, LockState.UNLOCKED),
        (False, True, LockState.LOCKED),
        (None, None, None),
        (1, None, None),
        (0, None, None),
        ("true", None, None),
    ],
)
def test_state_is_derived_from_exact_boolean_motor_state(
    hass,
    motor_state: object,
    expected_locked: bool | None,
    expected_state: LockState | None,
) -> None:
    """Only exact boolean motor values define the physical lock state."""
    entity = _entity(hass, AsyncMock(), _motor_property(motor_state))

    assert entity.is_locked is expected_locked
    assert entity.state == expected_state


def test_missing_motor_state_is_unknown(hass) -> None:
    """A missing motor datapoint produces unknown state without crashing."""
    entity = _entity(hass, AsyncMock(), {})

    assert entity.is_locked is None
    assert entity.state is None


def test_availability_follows_coordinator_refresh_success(hass) -> None:
    """The shared coordinator controls lock availability."""
    entity = _entity(hass, AsyncMock(), {})

    assert entity.available is True

    entity.coordinator.last_update_success = False
    assert entity.available is False


def test_identity_device_info_and_polling_remain_stable(hass) -> None:
    """The replacement lock preserves registry identity and shared metadata."""
    entity = _entity(hass, AsyncMock(), _motor_property(False))

    assert entity.unique_id == f"tuya_smart_lock_{DEVICE_ID}"
    assert entity.device_info == {
        "identifiers": {("tuya", DEVICE_ID)},
        "name": DEVICE_NAME,
        "manufacturer": "Tuya",
    }
    assert entity.should_poll is False


@pytest.mark.parametrize(
    ("method_name", "open_value", "transition_property", "transition_state"),
    [
        ("async_lock", False, "is_locking", LockState.LOCKING),
        ("async_unlock", True, "is_unlocking", LockState.UNLOCKING),
    ],
)
async def test_command_exposes_transition_and_calls_operate_lock(
    hass,
    method_name: str,
    open_value: bool,
    transition_property: str,
    transition_state: LockState,
) -> None:
    """Both lock commands expose transition state while Tuya is operating."""
    api = AsyncMock()
    operation_started = asyncio.Event()
    release_operation = asyncio.Event()

    async def operate_lock(device_id: str, *, open_: bool) -> None:
        assert device_id == DEVICE_ID
        assert open_ is open_value
        operation_started.set()
        await release_operation.wait()

    api.async_operate_lock.side_effect = operate_lock
    api.async_get_properties.return_value = _motor_property(open_value)
    entity = _entity(hass, api, _motor_property(not open_value))

    with patch(
        "custom_components.tuya_smart_lock.lock.async_sleep",
        new=AsyncMock(),
    ) as sleep:
        task = asyncio.create_task(getattr(entity, method_name)())
        await operation_started.wait()

        assert getattr(entity, transition_property) is True
        assert entity.state == transition_state

        release_operation.set()
        await task

    api.async_operate_lock.assert_awaited_once_with(
        DEVICE_ID,
        open_=open_value,
    )
    sleep.assert_awaited_once_with(2)
    assert getattr(entity, transition_property) is False
    assert entity.is_locked is (not open_value)
    assert entity.async_write_ha_state.call_count >= 2


async def test_opposite_commands_are_serialized_through_confirmation(hass) -> None:
    """A second command waits for the first command's complete lifecycle."""
    api = AsyncMock()
    first_api_started = asyncio.Event()
    release_first_api = asyncio.Event()
    first_confirmation_started = asyncio.Event()
    release_first_confirmation = asyncio.Event()
    second_api_started = asyncio.Event()
    release_second_api = asyncio.Event()
    operations: list[bool] = []

    async def operate_lock(device_id: str, *, open_: bool) -> None:
        assert device_id == DEVICE_ID
        operations.append(open_)
        if open_:
            second_api_started.set()
            await release_second_api.wait()
            return
        first_api_started.set()
        await release_first_api.wait()

    api.async_operate_lock.side_effect = operate_lock
    api.async_get_properties.side_effect = [
        _motor_property(False),
        _motor_property(True),
    ]
    entity = _entity(hass, api, _motor_property(True))
    first_task = None

    async def controlled_sleep(delay: int) -> None:
        assert delay == 2
        if asyncio.current_task() is first_task:
            first_confirmation_started.set()
            await release_first_confirmation.wait()

    with patch(
        "custom_components.tuya_smart_lock.lock.async_sleep",
        side_effect=controlled_sleep,
    ):
        first_task = asyncio.create_task(entity.async_lock())
        await first_api_started.wait()
        assert entity.is_locking is True
        assert entity.is_unlocking is False

        second_task = asyncio.create_task(entity.async_unlock())
        try:
            await asyncio.sleep(0)
            assert second_api_started.is_set() is False
            assert operations == [False]
            assert entity.is_locking is True
            assert entity.is_unlocking is False

            release_first_api.set()
            await first_confirmation_started.wait()
            assert second_api_started.is_set() is False
            assert entity.is_locking is True
            assert entity.is_unlocking is False

            release_first_confirmation.set()
            await second_api_started.wait()
            assert first_task.done() is True
            assert operations == [False, True]
            assert entity.is_locking is False
            assert entity.is_unlocking is True

            release_second_api.set()
            await asyncio.gather(first_task, second_task)
        finally:
            release_first_api.set()
            release_first_confirmation.set()
            release_second_api.set()
            await asyncio.gather(
                first_task,
                second_task,
                return_exceptions=True,
            )

    assert operations == [False, True]
    assert entity.is_locking is False
    assert entity.is_unlocking is False


async def test_cancelling_command_waiting_for_serialization_preserves_flags(
    hass,
) -> None:
    """Cancelling a queued command cannot disturb the active transition."""
    api = AsyncMock()
    first_api_started = asyncio.Event()
    release_first_api = asyncio.Event()
    release_second_api = asyncio.Event()
    operations: list[bool] = []

    async def operate_lock(device_id: str, *, open_: bool) -> None:
        assert device_id == DEVICE_ID
        operations.append(open_)
        if open_:
            await release_second_api.wait()
            return
        first_api_started.set()
        await release_first_api.wait()

    api.async_operate_lock.side_effect = operate_lock
    api.async_get_properties.return_value = _motor_property(False)
    entity = _entity(hass, api, _motor_property(True))

    with patch(
        "custom_components.tuya_smart_lock.lock.async_sleep",
        new=AsyncMock(),
    ):
        first_task = asyncio.create_task(entity.async_lock())
        await first_api_started.wait()
        second_task = asyncio.create_task(entity.async_unlock())
        try:
            await asyncio.sleep(0)

            second_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second_task

            assert operations == [False]
            assert entity.is_locking is True
            assert entity.is_unlocking is False

            release_first_api.set()
            await first_task
        finally:
            release_first_api.set()
            release_second_api.set()
            await asyncio.gather(
                first_task,
                second_task,
                return_exceptions=True,
            )

    assert entity.is_locking is False
    assert entity.is_unlocking is False


async def test_confirmation_refreshes_at_cumulative_two_five_and_ten_seconds(
    hass,
) -> None:
    """An unchanged lock is checked at all three bounded confirmation times."""
    api = AsyncMock()
    initial = properties_by_code(
        {
            "result": {
                "properties": [
                    {
                        "code": "lock_motor_state",
                        "value": False,
                        "time": 1_700_000_000,
                        "dp_id": 1,
                    }
                ]
            }
        }
    )
    assert initial["lock_motor_state"].timestamp_ms == TIMESTAMP_MS
    api.async_get_properties.side_effect = [initial, initial, initial]
    entity = _entity(hass, api, initial)

    with patch(
        "custom_components.tuya_smart_lock.lock.async_sleep",
        new=AsyncMock(),
    ) as sleep:
        with pytest.raises(
            HomeAssistantError,
            match="^Tuya accepted the lock command but the physical state "
            "was not confirmed[.]$",
        ):
            await entity.async_unlock()

    assert sleep.await_args_list == [call(2), call(3), call(5)]
    assert api.async_get_properties.await_count == 3
    assert entity.is_locked is True
    assert entity.coordinator.data["lock_motor_state"].timestamp_ms == TIMESTAMP_MS
    assert entity.is_unlocking is False


async def test_confirmation_stops_after_first_exact_matching_refresh(hass) -> None:
    """A matching physical state stops later confirmation refreshes."""
    api = AsyncMock()
    api.async_get_properties.return_value = _motor_property(True)
    entity = _entity(hass, api, _motor_property(False))

    with patch(
        "custom_components.tuya_smart_lock.lock.async_sleep",
        new=AsyncMock(),
    ) as sleep:
        await entity.async_unlock()

    sleep.assert_awaited_once_with(2)
    api.async_get_properties.assert_awaited_once_with(DEVICE_ID)
    assert entity.is_locked is False


async def test_non_boolean_matching_value_does_not_confirm(hass) -> None:
    """Truthy integer motor values cannot confirm an unlock command."""
    api = AsyncMock()
    api.async_get_properties.side_effect = [
        _motor_property(1),
        _motor_property(True),
    ]
    entity = _entity(hass, api, _motor_property(False))

    with patch(
        "custom_components.tuya_smart_lock.lock.async_sleep",
        new=AsyncMock(),
    ) as sleep:
        await entity.async_unlock()

    assert sleep.await_args_list == [call(2), call(3)]
    assert api.async_get_properties.await_count == 2
    assert entity.is_locked is False


@pytest.mark.parametrize(
    "error",
    [
        TuyaAuthenticationError("secret-token property-value"),
        TuyaAuthorizationError("secret-token property-value"),
        TuyaRateLimitError("secret-token property-value"),
        TuyaCommandError("secret-token property-value"),
        TuyaApiError("secret-token property-value"),
    ],
    ids=["authentication", "authorization", "rate-limit", "command", "api"],
)
async def test_api_errors_are_sanitized_and_preserve_confirmed_state(
    hass,
    error: TuyaApiError,
) -> None:
    """Typed command failures become a fixed safe Home Assistant error."""
    api = AsyncMock()
    api.async_operate_lock.side_effect = error
    initial = _motor_property(False)
    entity = _entity(hass, api, initial)

    with (
        patch(
            "custom_components.tuya_smart_lock.lock.async_sleep",
            new=AsyncMock(),
        ) as sleep,
        pytest.raises(
            HomeAssistantError,
            match="^Unable to operate the Tuya smart lock[.]$",
        ) as exc_info,
    ):
        await entity.async_unlock()

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
    assert "secret-token" not in str(exc_info.value)
    assert "property-value" not in str(exc_info.value)
    assert entity.coordinator.data is initial
    assert entity.is_locked is True
    assert entity.is_unlocking is False
    api.async_get_properties.assert_not_awaited()
    sleep.assert_not_awaited()


async def test_failed_refresh_cannot_confirm_from_retained_matching_data(
    hass,
    caplog,
) -> None:
    """A stale matching value is ignored while refresh availability is false."""
    api = AsyncMock()
    api.async_get_properties.side_effect = TuyaApiError(
        "secret-token property-value"
    )
    initial = _motor_property(False)
    entity = _entity(hass, api, initial)

    with patch(
        "custom_components.tuya_smart_lock.lock.async_sleep",
        new=AsyncMock(),
    ) as sleep:
        with pytest.raises(HomeAssistantError):
            await entity.async_lock()

    assert sleep.await_args_list == [call(2), call(3), call(5)]
    assert api.async_get_properties.await_count == 3
    assert entity.coordinator.last_update_success is False
    assert entity.coordinator.data is initial
    assert entity.is_locked is True
    assert entity.is_locking is False
    assert "secret-token" not in caplog.text
    assert "property-value" not in caplog.text


async def test_failed_refresh_then_successful_match_confirms(hass) -> None:
    """Confirmation continues after a failed refresh and accepts recovery."""
    api = AsyncMock()
    initial = _motor_property(False)
    api.async_get_properties.side_effect = [
        TuyaApiError("temporary failure"),
        _motor_property(False, timestamp_ms=TIMESTAMP_MS + 5_000),
    ]
    entity = _entity(hass, api, initial)

    with patch(
        "custom_components.tuya_smart_lock.lock.async_sleep",
        new=AsyncMock(),
    ) as sleep:
        await entity.async_lock()

    assert sleep.await_args_list == [call(2), call(3)]
    assert api.async_get_properties.await_count == 2
    assert entity.coordinator.last_update_success is True
    assert entity.is_locked is True
    assert entity.is_locking is False


@pytest.mark.parametrize(
    ("method_name", "flag_name"),
    [("async_lock", "is_locking"), ("async_unlock", "is_unlocking")],
)
async def test_unconfirmed_commands_always_clear_transition_flags(
    hass,
    method_name: str,
    flag_name: str,
) -> None:
    """The try/finally cleanup applies to both unconfirmed command paths."""
    api = AsyncMock()
    initial_value = method_name == "async_lock"
    unchanged = _motor_property(initial_value)
    api.async_get_properties.side_effect = [unchanged, unchanged, unchanged]
    entity = _entity(hass, api, unchanged)

    with patch(
        "custom_components.tuya_smart_lock.lock.async_sleep",
        new=AsyncMock(),
    ):
        with pytest.raises(HomeAssistantError):
            await getattr(entity, method_name)()

    assert getattr(entity, flag_name) is False
