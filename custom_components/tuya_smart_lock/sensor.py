"""Sensor platform for the Tuya Smart Lock integration."""

from math import isfinite

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TuyaSmartLockRuntimeData
from .const import DOMAIN
from .coordinator import TuyaSmartLockCoordinator
from .entity import TuyaSmartLockEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the coordinator-backed battery sensor."""
    runtime: TuyaSmartLockRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TuyaSmartLockBatterySensor(
                runtime.coordinator,
                device_id=runtime.device_id,
                device_name=runtime.device_name,
            )
        ]
    )


class TuyaSmartLockBatterySensor(TuyaSmartLockEntity, SensorEntity):
    """Represent the lock battery percentage."""

    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: TuyaSmartLockCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the battery sensor."""
        super().__init__(
            coordinator,
            device_id=device_id,
            device_name=device_name,
            unique_key="battery",
        )

    @property
    def native_value(self) -> int | float | None:
        """Return the first valid battery percentage datapoint."""
        for code in ("battery_percentage", "residual_electricity"):
            prop = self.coordinator.data.get(code)
            if prop is None:
                continue
            value = prop.value
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                return value
            if isinstance(value, float) and isfinite(value):
                return value
        return None
