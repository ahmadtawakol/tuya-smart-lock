"""Shared entity support for the Tuya Smart Lock integration."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import TuyaSmartLockCoordinator


class TuyaSmartLockEntity(CoordinatorEntity[TuyaSmartLockCoordinator]):
    """Provide common identity and device metadata for Tuya lock entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TuyaSmartLockCoordinator,
        device_id: str,
        device_name: str,
        unique_key: str,
    ) -> None:
        """Initialize common Tuya entity attributes."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{device_id}_{unique_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={("tuya", device_id)},
            name=device_name,
            manufacturer="Tuya",
        )
