"""Tests for the Tuya Smart Lock sensor platform."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, STATE_UNKNOWN
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components
from custom_components.tuya_smart_lock import TuyaSmartLockRuntimeData
from custom_components.tuya_smart_lock.const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_API_REGION,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    DOMAIN,
)
from custom_components.tuya_smart_lock.coordinator import TuyaSmartLockCoordinator
from custom_components.tuya_smart_lock.models import TuyaProperty
from custom_components.tuya_smart_lock.sensor import (
    TuyaSmartLockBatterySensor,
    async_setup_entry,
)

ENTRY_ID = "entry-123"
DEVICE_ID = "device-123"
DEVICE_NAME = "Front Door"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, entry_id=ENTRY_ID)


def _real_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        data={
            CONF_ACCESS_ID: "dummy-access-id",
            CONF_ACCESS_SECRET: "dummy-access-secret",
            CONF_API_REGION: "eu",
            CONF_DEVICE_ID: DEVICE_ID,
            CONF_DEVICE_NAME: DEVICE_NAME,
        },
    )
    entry.add_to_hass(hass)
    return entry


def _valid_custom_component_paths() -> list[str]:
    return [path for path in custom_components.__path__ if Path(path).is_dir()]


def _property(code: str, value: object) -> TuyaProperty:
    return TuyaProperty(code=code, value=value, timestamp_ms=None, dp_id=None)


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
    coordinator.async_set_updated_data(data or {})
    return coordinator


def _entity(
    hass,
    data: dict[str, TuyaProperty] | None = None,
) -> TuyaSmartLockBatterySensor:
    return TuyaSmartLockBatterySensor(
        _coordinator(hass, data),
        device_id=DEVICE_ID,
        device_name=DEVICE_NAME,
    )


async def _real_battery_state(hass, data: dict[str, TuyaProperty]) -> str:
    """Return the battery state after a real entity-platform attachment."""
    entry = _real_entry(hass)
    api = AsyncMock()
    api.async_get_properties.return_value = data

    with (
        patch.object(
            custom_components,
            "__path__",
            _valid_custom_component_paths(),
        ),
        patch(
            "custom_components.tuya_smart_lock.TuyaCloudApi",
            return_value=api,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id) is True
        await hass.async_block_till_done()

        entity_id = er.async_get(hass).async_get_entity_id(
            "sensor",
            DOMAIN,
            f"{DEVICE_ID}_battery",
        )
        assert entity_id is not None
        state = hass.states.get(entity_id)
        assert state is not None

        assert await hass.config_entries.async_unload(entry.entry_id) is True
        await hass.async_block_till_done()

    return state.state


async def test_setup_reads_typed_runtime_and_adds_one_entity(hass) -> None:
    """Platform setup always adds one coordinator-backed battery sensor."""
    entry = _entry()
    api = AsyncMock()
    coordinator = _coordinator(hass)
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
    assert isinstance(entities[0], TuyaSmartLockBatterySensor)
    assert entities[0].coordinator is coordinator


@pytest.mark.parametrize("value", [0, 72, -1, 101, 12.5])
def test_battery_percentage_accepts_finite_numeric_values(hass, value) -> None:
    """Battery values pass through without clamping or conversion."""
    entity = _entity(
        hass,
        {"battery_percentage": _property("battery_percentage", value)},
    )

    assert entity.native_value == value
    assert type(entity.native_value) is type(value)


def test_battery_percentage_takes_precedence_over_residual_electricity(
    hass,
) -> None:
    """The primary battery datapoint wins when it is valid."""
    entity = _entity(
        hass,
        {
            "battery_percentage": _property("battery_percentage", 64),
            "residual_electricity": _property("residual_electricity", 38),
        },
    )

    assert entity.native_value == 64


@pytest.mark.parametrize(
    "invalid_primary",
    [True, False, "64", None, float("inf"), float("-inf"), float("nan")],
)
def test_invalid_primary_uses_valid_residual_electricity(
    hass,
    invalid_primary: object,
) -> None:
    """A valid fallback is used when the primary value is invalid."""
    entity = _entity(
        hass,
        {
            "battery_percentage": _property("battery_percentage", invalid_primary),
            "residual_electricity": _property("residual_electricity", 47.5),
        },
    )

    assert entity.native_value == 47.5


async def test_unrepresentable_primary_uses_valid_fallback_without_state_error(
    hass,
) -> None:
    """A huge primary integer cannot break HA state or block the fallback."""
    state = await _real_battery_state(
        hass,
        {
            "battery_percentage": _property("battery_percentage", 10**400),
            "residual_electricity": _property("residual_electricity", 38),
        },
    )

    assert state == "38"


@pytest.mark.parametrize(
    "invalid_fallback",
    [True, False, "47", None, float("inf"), float("nan")],
)
def test_invalid_residual_electricity_is_unknown(
    hass,
    invalid_fallback: object,
) -> None:
    """Non-numeric and non-finite fallback values are rejected."""
    entity = _entity(
        hass,
        {"residual_electricity": _property("residual_electricity", invalid_fallback)},
    )

    assert entity.native_value is None


async def test_unrepresentable_fallback_is_unknown_without_state_error(hass) -> None:
    """A huge fallback integer produces unknown state without overflowing."""
    state = await _real_battery_state(
        hass,
        {
            "residual_electricity": _property(
                "residual_electricity",
                10**400,
            )
        },
    )

    assert state == STATE_UNKNOWN


def test_missing_battery_datapoints_are_unknown(hass) -> None:
    """The entity remains present with unknown state when data is missing."""
    assert _entity(hass).native_value is None


def test_battery_metadata_identity_availability_and_polling(hass) -> None:
    """The battery sensor exposes stable HA metadata and shared availability."""
    entity = _entity(hass)

    assert entity.device_class is SensorDeviceClass.BATTERY
    assert entity.native_unit_of_measurement == PERCENTAGE
    assert entity.state_class is SensorStateClass.MEASUREMENT
    assert entity.unique_id == f"{DEVICE_ID}_battery"
    assert entity.device_info == {
        "identifiers": {("tuya", DEVICE_ID)},
        "name": DEVICE_NAME,
        "manufacturer": "Tuya",
    }
    assert entity.should_poll is False
    assert entity.available is True

    entity.coordinator.last_update_success = False
    assert entity.available is False
