"""Event platform for the Tuya Smart Lock integration."""

from typing import Any

from homeassistant.components.event import (
    DoorbellEventType,
    EventDeviceClass,
    EventEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TuyaSmartLockRuntimeData
from .const import DOMAIN, UNLOCK_EVENT_TYPES_BY_CODE
from .coordinator import TuyaSmartLockCoordinator
from .entity import TuyaSmartLockEntity
from .models import TuyaProperty


def _valid_timestamp_ms(prop: TuyaProperty | None) -> int | None:
    """Return a normalized timestamp and reject malformed runtime data."""
    if prop is None:
        return None
    timestamp_ms = prop.timestamp_ms
    if type(timestamp_ms) is not int or timestamp_ms < 0:
        return None
    return timestamp_ms


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up timestamp-aware Tuya lock event entities."""
    runtime: TuyaSmartLockRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TuyaSmartLockDoorbellEvent(
                runtime.coordinator,
                device_id=runtime.device_id,
                device_name=runtime.device_name,
            ),
            TuyaSmartLockOpenedInsideEvent(
                runtime.coordinator,
                device_id=runtime.device_id,
                device_name=runtime.device_name,
            ),
            TuyaSmartLockAlarmEvent(
                runtime.coordinator,
                device_id=runtime.device_id,
                device_name=runtime.device_name,
            ),
            TuyaSmartLockUnlockEvent(
                runtime.coordinator,
                device_id=runtime.device_id,
                device_name=runtime.device_name,
            ),
        ]
    )


class _TuyaSmartLockTimestampEvent(TuyaSmartLockEntity, EventEntity):
    """Base entity for a single timestamped Tuya event datapoint."""

    _attr_should_poll = False
    _source_code: str
    _event_type: str

    def __init__(
        self,
        coordinator: TuyaSmartLockCoordinator,
        device_id: str,
        device_name: str,
        unique_key: str,
    ) -> None:
        """Initialize a timestamp-aware event entity."""
        super().__init__(
            coordinator,
            device_id=device_id,
            device_name=device_name,
            unique_key=unique_key,
        )
        self._last_timestamp_ms: int | None = None

    async def async_added_to_hass(self) -> None:
        """Register for updates and seed the current historical timestamp."""
        await super().async_added_to_hass()
        self._last_timestamp_ms = _valid_timestamp_ms(
            self.coordinator.data.get(self._source_code)
        )

    def _event_attributes(self, prop: TuyaProperty) -> dict[str, Any] | None:
        """Return safe attributes for the current event."""
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Emit an event only when its source timestamp advances."""
        prop = self.coordinator.data.get(self._source_code)
        if prop is None:
            super()._handle_coordinator_update()
            return
        timestamp_ms = _valid_timestamp_ms(prop)
        if timestamp_ms is None or (
            self._last_timestamp_ms is not None
            and timestamp_ms <= self._last_timestamp_ms
        ):
            super()._handle_coordinator_update()
            return

        self._last_timestamp_ms = timestamp_ms
        self._trigger_event(self._event_type, self._event_attributes(prop))
        self.async_write_ha_state()


class TuyaSmartLockDoorbellEvent(_TuyaSmartLockTimestampEvent):
    """Represent doorbell rings reported by the lock."""

    _attr_name = "Doorbell"
    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = [DoorbellEventType.RING]
    _source_code = "doorbell"
    _event_type = DoorbellEventType.RING

    def __init__(
        self,
        coordinator: TuyaSmartLockCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the doorbell event entity."""
        super().__init__(
            coordinator,
            device_id=device_id,
            device_name=device_name,
            unique_key="doorbell",
        )


class TuyaSmartLockOpenedInsideEvent(_TuyaSmartLockTimestampEvent):
    """Represent the lock being opened from inside."""

    _attr_name = "Opened inside"
    _attr_event_types = ["opened"]
    _source_code = "open_inside"
    _event_type = "opened"

    def __init__(
        self,
        coordinator: TuyaSmartLockCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the inside-open event entity."""
        super().__init__(
            coordinator,
            device_id=device_id,
            device_name=device_name,
            unique_key="opened_inside",
        )


class TuyaSmartLockAlarmEvent(_TuyaSmartLockTimestampEvent):
    """Represent lock alarm events."""

    _attr_name = "Lock alarm"
    _attr_event_types = ["alarm"]
    _source_code = "alarm_lock"
    _event_type = "alarm"

    def __init__(
        self,
        coordinator: TuyaSmartLockCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the lock alarm event entity."""
        super().__init__(
            coordinator,
            device_id=device_id,
            device_name=device_name,
            unique_key="lock_alarm",
        )

    def _event_attributes(self, prop: TuyaProperty) -> dict[str, Any] | None:
        """Expose non-empty alarm reasons without leaking invalid values."""
        if isinstance(prop.value, str) and prop.value:
            return {"reason": prop.value}
        return None


class TuyaSmartLockUnlockEvent(TuyaSmartLockEntity, EventEntity):
    """Represent all supported unlock methods on one event entity."""

    _attr_name = "Unlocked"
    _attr_event_types = list(UNLOCK_EVENT_TYPES_BY_CODE.values())
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: TuyaSmartLockCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the unified unlock event entity."""
        super().__init__(
            coordinator,
            device_id=device_id,
            device_name=device_name,
            unique_key="unlocked",
        )
        self._last_timestamps_ms: dict[str, int | None] = {
            code: None for code in UNLOCK_EVENT_TYPES_BY_CODE
        }

    async def async_added_to_hass(self) -> None:
        """Register for updates and seed each unlock source cursor."""
        await super().async_added_to_hass()
        for code in UNLOCK_EVENT_TYPES_BY_CODE:
            self._last_timestamps_ms[code] = _valid_timestamp_ms(
                self.coordinator.data.get(code)
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Emit advanced unlock events in deterministic timestamp/code order."""
        advanced: list[tuple[int, str, TuyaProperty]] = []
        for code in UNLOCK_EVENT_TYPES_BY_CODE:
            prop = self.coordinator.data.get(code)
            if prop is None:
                continue
            timestamp_ms = _valid_timestamp_ms(prop)
            last_timestamp_ms = self._last_timestamps_ms[code]
            if timestamp_ms is None or (
                last_timestamp_ms is not None and timestamp_ms <= last_timestamp_ms
            ):
                continue
            advanced.append((timestamp_ms, code, prop))

        if not advanced:
            super()._handle_coordinator_update()
            return

        for timestamp_ms, code, prop in sorted(advanced):
            self._last_timestamps_ms[code] = timestamp_ms
            attributes = (
                {"credential_id": prop.value} if type(prop.value) is int else None
            )
            self._trigger_event(UNLOCK_EVENT_TYPES_BY_CODE[code], attributes)
            self.async_write_ha_state()
