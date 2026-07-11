"""Lock entity for Tuya Smart Lock."""

from asyncio import Lock
from asyncio import sleep as async_sleep
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TuyaSmartLockRuntimeData
from .const import CONFIRMATION_DELAYS, DOMAIN
from .coordinator import TuyaSmartLockCoordinator
from .entity import TuyaSmartLockEntity
from .errors import TuyaApiError

COMMAND_ERROR = "Unable to operate the Tuya smart lock."
CONFIRMATION_ERROR = (
    "Tuya accepted the lock command but the physical state was not confirmed."
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the coordinator-backed lock entity."""
    runtime: TuyaSmartLockRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TuyaSmartLock(
                runtime.coordinator,
                device_id=runtime.device_id,
                device_name=runtime.device_name,
            )
        ]
    )


class TuyaSmartLock(TuyaSmartLockEntity, LockEntity):
    """Represent the physically confirmed state of a Tuya smart lock."""

    _attr_name = None
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: TuyaSmartLockCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the lock entity."""
        super().__init__(
            coordinator,
            device_id=device_id,
            device_name=device_name,
            unique_key="lock",
        )
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}"
        self._attr_is_locking = False
        self._attr_is_unlocking = False
        self._operation_lock = Lock()

    @property
    def is_locked(self) -> bool | None:
        """Return the lock state derived from the motor datapoint."""
        motor_state = self._motor_state
        if motor_state is None:
            return None
        return not motor_state

    @property
    def is_locking(self) -> bool:
        """Return whether a lock command is in progress."""
        return self._attr_is_locking

    @property
    def is_unlocking(self) -> bool:
        """Return whether an unlock command is in progress."""
        return self._attr_is_unlocking

    @property
    def _motor_state(self) -> bool | None:
        """Return only an exact boolean motor datapoint value."""
        if not self.coordinator.data:
            return None
        prop = self.coordinator.data.get("lock_motor_state")
        if prop is None:
            return None
        if prop.value is True:
            return True
        if prop.value is False:
            return False
        return None

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the door and wait for physical confirmation."""
        await self._async_operate(open_=False)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the door and wait for physical confirmation."""
        await self._async_operate(open_=True)

    async def _async_operate(self, *, open_: bool) -> None:
        """Send a lock command and confirm the resulting motor state."""
        async with self._operation_lock:
            self._attr_is_locking = not open_
            self._attr_is_unlocking = open_
            self.async_write_ha_state()

            try:
                try:
                    await self.coordinator.api.async_operate_lock(
                        self._device_id,
                        open_=open_,
                    )
                except TuyaApiError:
                    raise HomeAssistantError(COMMAND_ERROR) from None

                for delay in CONFIRMATION_DELAYS:
                    await async_sleep(delay)
                    await self.coordinator.async_refresh()
                    if (
                        self.coordinator.last_update_success
                        and self._motor_state is open_
                    ):
                        return

                raise HomeAssistantError(CONFIRMATION_ERROR)
            finally:
                self._attr_is_locking = False
                self._attr_is_unlocking = False
                self.async_write_ha_state()
