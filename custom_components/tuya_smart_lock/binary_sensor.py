"""Binary sensor platform for Tuya Smart Lock."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
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
    """Set up the coordinator-backed hijack safety sensor."""
    runtime: TuyaSmartLockRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TuyaSmartLockHijackBinarySensor(
                runtime.coordinator,
                device_id=runtime.device_id,
                device_name=runtime.device_name,
            )
        ]
    )


class TuyaSmartLockHijackBinarySensor(TuyaSmartLockEntity, BinarySensorEntity):
    """Represent the lock's hijack safety alarm."""

    _attr_name = "Hijack"
    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: TuyaSmartLockCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the hijack safety sensor."""
        super().__init__(
            coordinator,
            device_id=device_id,
            device_name=device_name,
            unique_key="hijack",
        )

    @property
    def is_on(self) -> bool | None:
        """Return only an exact boolean hijack datapoint value."""
        prop = self.coordinator.data.get("hijack")
        if prop is None:
            return None
        if prop.value is True:
            return True
        if prop.value is False:
            return False
        return None
