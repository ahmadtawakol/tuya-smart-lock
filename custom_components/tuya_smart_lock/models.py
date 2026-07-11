"""Normalized models for Tuya shadow-property responses."""

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite

SECONDS_TIMESTAMP_CUTOFF = 100_000_000_000


@dataclass(frozen=True)
class TuyaProperty:
    """A normalized Tuya shadow property."""

    code: str
    value: object
    timestamp_ms: int | None
    dp_id: int | None


def normalize_timestamp_ms(value: object) -> int | None:
    """Normalize a numeric Unix timestamp to milliseconds."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if value < 0 or not isfinite(value):
        return None
    if value < SECONDS_TIMESTAMP_CUTOFF:
        value *= 1000
    return int(value)


def properties_by_code(payload: object) -> dict[str, TuyaProperty]:
    """Return valid Tuya shadow properties keyed by datapoint code."""
    if not isinstance(payload, Mapping):
        return {}

    result = payload.get("result")
    if not isinstance(result, Mapping):
        return {}

    records = result.get("properties")
    if not isinstance(records, list):
        return {}

    properties: dict[str, TuyaProperty] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        code = record.get("code")
        if not isinstance(code, str) or not code:
            continue
        dp_id = record.get("dp_id")
        normalized_dp_id = (
            dp_id if isinstance(dp_id, int) and not isinstance(dp_id, bool) else None
        )
        properties[code] = TuyaProperty(
            code=code,
            value=record.get("value"),
            timestamp_ms=normalize_timestamp_ms(record.get("time")),
            dp_id=normalized_dp_id,
        )

    return properties
