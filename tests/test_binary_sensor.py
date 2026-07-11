"""Tests for the Tuya Smart Lock binary sensor platform."""

from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_smart_lock import TuyaSmartLockRuntimeData
from custom_components.tuya_smart_lock.binary_sensor import (
    TuyaSmartLockHijackBinarySensor,
    async_setup_entry,
)
from custom_components.tuya_smart_lock.const import DOMAIN
from custom_components.tuya_smart_lock.coordinator import TuyaSmartLockCoordinator
from custom_components.tuya_smart_lock.models import TuyaProperty

ENTRY_ID = "entry-123"
DEVICE_ID = "device-123"
DEVICE_NAME = "Front Door"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, entry_id=ENTRY_ID)


def _coordinator(
    hass,
    value: object = None,
    *,
    include_hijack: bool = True,
) -> TuyaSmartLockCoordinator:
    coordinator = TuyaSmartLockCoordinator(
        hass,
        AsyncMock(),
        DEVICE_ID,
        _entry(),
    )
    data = (
        {
            "hijack": TuyaProperty(
                code="hijack",
                value=value,
                timestamp_ms=None,
                dp_id=None,
            )
        }
        if include_hijack
        else {}
    )
    coordinator.async_set_updated_data(data)
    return coordinator


def _entity(
    hass,
    value: object = None,
    *,
    include_hijack: bool = True,
) -> TuyaSmartLockHijackBinarySensor:
    return TuyaSmartLockHijackBinarySensor(
        _coordinator(hass, value, include_hijack=include_hijack),
        device_id=DEVICE_ID,
        device_name=DEVICE_NAME,
    )


async def test_setup_reads_typed_runtime_and_adds_one_entity(hass) -> None:
    """Platform setup always adds one coordinator-backed hijack sensor."""
    entry = _entry()
    api = AsyncMock()
    coordinator = _coordinator(hass, include_hijack=False)
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
    assert isinstance(entities[0], TuyaSmartLockHijackBinarySensor)
    assert entities[0].coordinator is coordinator


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (None, None),
        (0, None),
        (1, None),
        ("true", None),
    ],
)
def test_hijack_state_requires_an_exact_boolean(
    hass,
    value: object,
    expected: bool | None,
) -> None:
    """Only exact booleans define the hijack safety state."""
    assert _entity(hass, value).is_on is expected


def test_missing_hijack_datapoint_is_unknown(hass) -> None:
    """The entity remains present with unknown state when data is missing."""
    assert _entity(hass, include_hijack=False).is_on is None


def test_hijack_metadata_identity_availability_and_polling(hass) -> None:
    """The hijack sensor exposes stable metadata and shared availability."""
    entity = _entity(hass, False)

    assert entity.device_class is BinarySensorDeviceClass.SAFETY
    assert entity.unique_id == f"{DEVICE_ID}_hijack"
    assert entity.device_info == {
        "identifiers": {("tuya", DEVICE_ID)},
        "name": DEVICE_NAME,
        "manufacturer": "Tuya",
    }
    assert entity.should_poll is False
    assert entity.available is True

    entity.coordinator.last_update_success = False
    assert entity.available is False
