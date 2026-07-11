"""Tests for the Tuya Smart Lock event platform."""

from collections.abc import Mapping
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.event import DoorbellEventType, EventDeviceClass
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_smart_lock import TuyaSmartLockRuntimeData
from custom_components.tuya_smart_lock import event as event_platform
from custom_components.tuya_smart_lock.const import DOMAIN
from custom_components.tuya_smart_lock.coordinator import TuyaSmartLockCoordinator
from custom_components.tuya_smart_lock.models import TuyaProperty

ENTRY_ID = "entry-123"
DEVICE_ID = "device-123"
DEVICE_NAME = "Front Door"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, entry_id=ENTRY_ID)


def _property(
    code: str,
    value: object,
    timestamp_ms: object,
) -> TuyaProperty:
    return TuyaProperty(
        code=code,
        value=value,
        timestamp_ms=timestamp_ms,  # type: ignore[arg-type]
        dp_id=None,
    )


def _coordinator(
    hass,
    data: dict[str, TuyaProperty] | None = None,
) -> TuyaSmartLockCoordinator:
    coordinator = TuyaSmartLockCoordinator(
        hass,
        AsyncMock(),
        DEVICE_ID,
        _entry(),
    )
    coordinator.update_interval = None
    coordinator.async_set_updated_data(data or {})
    return coordinator


async def _setup_entities(
    hass,
    data: dict[str, TuyaProperty] | None = None,
):
    entry = _entry()
    coordinator = _coordinator(hass, data)
    hass.data[DOMAIN] = {
        ENTRY_ID: TuyaSmartLockRuntimeData(
            api=AsyncMock(),
            coordinator=coordinator,
            device_id=DEVICE_ID,
            device_name=DEVICE_NAME,
        )
    }
    async_add_entities = Mock()

    await event_platform.async_setup_entry(hass, entry, async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args.args[0]
    return coordinator, entities


async def _add_to_hass(entity, hass) -> Mock:
    entity.hass = hass
    writes = Mock()
    entity.async_write_ha_state = writes
    await entity.async_added_to_hass()
    return writes


def _entity_by_unique_id(entities, unique_id: str):
    return next(entity for entity in entities if entity.unique_id == unique_id)


async def test_setup_adds_four_linked_coordinator_event_entities(hass) -> None:
    """Setup creates four stable, linked, coordinator-backed event entities."""
    coordinator, entities = await _setup_entities(hass)

    assert {entity.unique_id for entity in entities} == {
        f"{DEVICE_ID}_doorbell",
        f"{DEVICE_ID}_opened_inside",
        f"{DEVICE_ID}_lock_alarm",
        f"{DEVICE_ID}_unlocked",
    }
    for entity in entities:
        assert entity.coordinator is coordinator
        assert entity.device_info == {
            "identifiers": {("tuya", DEVICE_ID)},
            "name": DEVICE_NAME,
            "manufacturer": "Tuya",
        }
        assert entity.should_poll is False
        assert entity.available is True

    coordinator.last_update_success = False
    assert all(entity.available is False for entity in entities)


async def test_adding_entities_seeds_current_timestamps_without_events(hass) -> None:
    """Existing cloud timestamps are historical state, not new events."""
    coordinator, entities = await _setup_entities(
        hass,
        {
            "doorbell": _property("doorbell", True, 100),
            "open_inside": _property("open_inside", True, 101),
            "alarm_lock": _property("alarm_lock", "alarm_illegal_user", 102),
            "unlock_card": _property("unlock_card", 7, 103),
            "unlock_fingerprint": _property("unlock_fingerprint", 8, 104),
        },
    )

    writes = [await _add_to_hass(entity, hass) for entity in entities]

    assert all(write.call_count == 0 for write in writes)
    assert all(entity.state is None for entity in entities)
    assert coordinator.data["doorbell"].timestamp_ms == 100


@pytest.mark.parametrize("invalid_timestamp", [None, True, "200", -1])
async def test_invalid_timestamp_does_not_emit_or_advance_cursor(
    hass,
    invalid_timestamp: object,
) -> None:
    """Malformed timestamps neither trigger an event nor suppress a later one."""
    coordinator, entities = await _setup_entities(
        hass,
        {"doorbell": _property("doorbell", True, 100)},
    )
    entity = _entity_by_unique_id(entities, f"{DEVICE_ID}_doorbell")
    writes = await _add_to_hass(entity, hass)

    coordinator.async_set_updated_data(
        {"doorbell": _property("doorbell", True, invalid_timestamp)}
    )
    assert writes.call_count == 0

    coordinator.async_set_updated_data(
        {"doorbell": _property("doorbell", True, 150)}
    )
    assert writes.call_count == 1
    assert entity.state_attributes == {"event_type": DoorbellEventType.RING}


@pytest.mark.parametrize("timestamp_ms", [100, 99])
async def test_same_or_older_timestamp_does_not_emit(
    hass,
    timestamp_ms: int,
) -> None:
    """A timestamp must advance beyond the source cursor to trigger."""
    coordinator, entities = await _setup_entities(
        hass,
        {"doorbell": _property("doorbell", True, 100)},
    )
    entity = _entity_by_unique_id(entities, f"{DEVICE_ID}_doorbell")
    writes = await _add_to_hass(entity, hass)

    coordinator.async_set_updated_data(
        {"doorbell": _property("doorbell", False, timestamp_ms)}
    )

    assert writes.call_count == 0
    assert entity.state is None


async def test_each_newer_doorbell_timestamp_emits_ring_even_if_value_repeats(
    hass,
) -> None:
    """Doorbell events are timestamp-driven rather than value-change-driven."""
    coordinator, entities = await _setup_entities(
        hass,
        {"doorbell": _property("doorbell", True, 100)},
    )
    entity = _entity_by_unique_id(entities, f"{DEVICE_ID}_doorbell")
    observed_events: list[tuple[object, Mapping[str, object]]] = []
    await _add_to_hass(entity, hass)
    entity.async_write_ha_state = Mock(
        side_effect=lambda: observed_events.append(
            (entity.state, dict(entity.state_attributes))
        )
    )

    coordinator.async_set_updated_data(
        {"doorbell": _property("doorbell", True, 101)}
    )
    coordinator.async_set_updated_data(
        {"doorbell": _property("doorbell", True, 101)}
    )
    coordinator.async_set_updated_data(
        {"doorbell": _property("doorbell", True, 102)}
    )

    assert [attributes for _, attributes in observed_events] == [
        {"event_type": DoorbellEventType.RING},
        {"event_type": DoorbellEventType.RING},
    ]


async def test_doorbell_declares_standard_device_class_and_ring_type(hass) -> None:
    """Doorbell metadata uses Home Assistant's standard ring event."""
    _, entities = await _setup_entities(hass)
    entity = _entity_by_unique_id(entities, f"{DEVICE_ID}_doorbell")

    assert entity.device_class is EventDeviceClass.DOORBELL
    assert entity.event_types == [DoorbellEventType.RING]


async def test_inside_open_emits_opened_on_new_timestamp(hass) -> None:
    """The inside-open datapoint is represented as a transient event."""
    coordinator, entities = await _setup_entities(
        hass,
        {"open_inside": _property("open_inside", True, 100)},
    )
    entity = _entity_by_unique_id(entities, f"{DEVICE_ID}_opened_inside")
    writes = await _add_to_hass(entity, hass)

    coordinator.async_set_updated_data(
        {"open_inside": _property("open_inside", True, 101)}
    )

    assert writes.call_count == 1
    assert entity.event_types == ["opened"]
    assert entity.state_attributes == {"event_type": "opened"}


@pytest.mark.parametrize("reason", ["alarm_illegal_user", "future_alarm_reason"])
async def test_alarm_exposes_any_non_empty_string_as_reason(
    hass,
    reason: str,
) -> None:
    """Documented and undocumented alarm strings are safe event attributes."""
    coordinator, entities = await _setup_entities(
        hass,
        {"alarm_lock": _property("alarm_lock", reason, 100)},
    )
    entity = _entity_by_unique_id(entities, f"{DEVICE_ID}_lock_alarm")
    writes = await _add_to_hass(entity, hass)

    coordinator.async_set_updated_data(
        {"alarm_lock": _property("alarm_lock", reason, 101)}
    )

    assert writes.call_count == 1
    assert entity.event_types == ["alarm"]
    assert entity.state_attributes == {
        "event_type": "alarm",
        "reason": reason,
    }


@pytest.mark.parametrize("value", [None, "", 7, True, {"raw": "secret"}])
async def test_alarm_invalid_reason_emits_without_leaking_value(
    hass,
    value: object,
) -> None:
    """Invalid alarm payloads may trigger but are never exposed as attributes."""
    coordinator, entities = await _setup_entities(
        hass,
        {"alarm_lock": _property("alarm_lock", "seed", 100)},
    )
    entity = _entity_by_unique_id(entities, f"{DEVICE_ID}_lock_alarm")
    writes = await _add_to_hass(entity, hass)

    coordinator.async_set_updated_data(
        {"alarm_lock": _property("alarm_lock", value, 101)}
    )

    assert writes.call_count == 1
    assert entity.state_attributes == {"event_type": "alarm"}


async def test_unlock_declares_complete_fixed_method_mapping(hass) -> None:
    """All supported Tuya unlock codes map to stable event types."""
    _, entities = await _setup_entities(hass)
    entity = _entity_by_unique_id(entities, f"{DEVICE_ID}_unlocked")

    assert event_platform.UNLOCK_EVENT_TYPES_BY_CODE == {
        "unlock_password": "password",
        "unlock_fingerprint": "fingerprint",
        "unlock_card": "card",
        "unlock_face": "face",
        "unlock_hand": "palm",
        "unlock_temporary": "temporary_code",
        "unlock_key": "physical_key",
        "unlock_phone_remote": "phone_remote",
        "unlock_dynamic": "dynamic_code",
    }
    assert entity.event_types == [
        "password",
        "fingerprint",
        "card",
        "face",
        "palm",
        "temporary_code",
        "physical_key",
        "phone_remote",
        "dynamic_code",
    ]


async def test_unlock_exposes_only_exact_integer_credential_id(hass) -> None:
    """A credential ID is emitted only when Tuya reports an exact integer."""
    coordinator, entities = await _setup_entities(
        hass,
        {"unlock_card": _property("unlock_card", 7, 100)},
    )
    entity = _entity_by_unique_id(entities, f"{DEVICE_ID}_unlocked")
    writes = await _add_to_hass(entity, hass)

    coordinator.async_set_updated_data(
        {"unlock_card": _property("unlock_card", 42, 101)}
    )

    assert writes.call_count == 1
    assert entity.state_attributes == {
        "event_type": "card",
        "credential_id": 42,
    }


@pytest.mark.parametrize(
    "credential",
    [True, False, None, "42", 42.0, {"credential": 42}],
)
async def test_unlock_invalid_credential_emits_without_leaking_value(
    hass,
    credential: object,
) -> None:
    """Invalid credential data never reaches the event state attributes."""
    coordinator, entities = await _setup_entities(
        hass,
        {"unlock_card": _property("unlock_card", 7, 100)},
    )
    entity = _entity_by_unique_id(entities, f"{DEVICE_ID}_unlocked")
    writes = await _add_to_hass(entity, hass)

    coordinator.async_set_updated_data(
        {"unlock_card": _property("unlock_card", credential, 101)}
    )

    assert writes.call_count == 1
    assert entity.state_attributes == {"event_type": "card"}


async def test_unlock_uses_one_cursor_per_code_and_orders_simultaneous_events(
    hass,
) -> None:
    """Advanced unlock sources emit independently in timestamp/code order."""
    coordinator, entities = await _setup_entities(
        hass,
        {
            "unlock_card": _property("unlock_card", 1, 100),
            "unlock_password": _property("unlock_password", 2, 200),
        },
    )
    entity = _entity_by_unique_id(entities, f"{DEVICE_ID}_unlocked")
    observed_events: list[dict[str, object]] = []
    await _add_to_hass(entity, hass)
    entity.async_write_ha_state = Mock(
        side_effect=lambda: observed_events.append(dict(entity.state_attributes))
    )

    coordinator.async_set_updated_data(
        {
            "unlock_password": _property("unlock_password", 20, 201),
            "unlock_fingerprint": _property("unlock_fingerprint", 30, 150),
            "unlock_card": _property("unlock_card", 10, 201),
        }
    )

    assert observed_events == [
        {"event_type": "fingerprint", "credential_id": 30},
        {"event_type": "card", "credential_id": 10},
        {"event_type": "password", "credential_id": 20},
    ]

    observed_events.clear()
    coordinator.async_set_updated_data(
        {
            "unlock_password": _property("unlock_password", 21, 201),
            "unlock_fingerprint": _property("unlock_fingerprint", 31, 151),
            "unlock_card": _property("unlock_card", 11, 200),
        }
    )

    assert observed_events == [
        {"event_type": "fingerprint", "credential_id": 31}
    ]
