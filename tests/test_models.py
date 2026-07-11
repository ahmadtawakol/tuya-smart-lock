"""Tests for normalized Tuya shadow properties."""

import pytest

from custom_components.tuya_smart_lock.models import (
    TuyaProperty,
    normalize_timestamp_ms,
    properties_by_code,
)


def test_normalize_timestamp_ms_keeps_milliseconds() -> None:
    """Milliseconds remain unchanged."""
    assert normalize_timestamp_ms(1_783_792_375_000) == 1_783_792_375_000


def test_normalize_timestamp_ms_converts_seconds() -> None:
    """Seconds are converted to milliseconds."""
    assert normalize_timestamp_ms(1_783_792_375) == 1_783_792_375_000


def test_normalize_timestamp_ms_handles_huge_integer() -> None:
    """Large integer timestamps do not overflow float conversion."""
    timestamp = 10**400

    assert normalize_timestamp_ms(timestamp) == timestamp


@pytest.mark.parametrize("timestamp", [float("nan"), float("inf"), float("-inf")])
def test_normalize_timestamp_ms_rejects_non_finite_float(timestamp: float) -> None:
    """NaN and positive or negative infinity are rejected."""
    assert normalize_timestamp_ms(timestamp) is None


@pytest.mark.parametrize("timestamp", [None, "bad", True, -1])
def test_normalize_timestamp_ms_rejects_invalid_values(timestamp: object) -> None:
    """Missing, non-numeric, boolean, and negative timestamps are rejected."""
    assert normalize_timestamp_ms(timestamp) is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"result": None},
        {"result": {}},
        {"result": {"properties": None}},
        {"result": {"properties": "not-a-list"}},
    ],
)
def test_properties_by_code_safely_reads_properties(payload: object) -> None:
    """Malformed or absent result properties produce an empty mapping."""
    assert properties_by_code(payload) == {}


def test_properties_by_code_ignores_records_without_valid_code() -> None:
    """Only records with non-empty string codes are retained."""
    payload = {
        "result": {
            "properties": [
                None,
                "not-a-record",
                {},
                {"code": None, "value": 1},
                {"code": "", "value": 2},
                {"code": 53, "value": 3},
                {"code": "doorbell", "value": True},
            ]
        }
    }

    assert set(properties_by_code(payload)) == {"doorbell"}


def test_properties_by_code_retains_normalized_record() -> None:
    """Property fields are preserved and timestamps are normalized."""
    payload = {
        "result": {
            "properties": [
                {
                    "code": "doorbell",
                    "dp_id": 53,
                    "time": 1_783_792_375,
                    "value": True,
                }
            ]
        }
    }

    assert properties_by_code(payload)["doorbell"] == TuyaProperty(
        code="doorbell",
        value=True,
        timestamp_ms=1_783_792_375_000,
        dp_id=53,
    )


def test_properties_by_code_keeps_last_duplicate() -> None:
    """The last record wins when Tuya returns a duplicate code."""
    payload = {
        "result": {
            "properties": [
                {"code": "doorbell", "dp_id": 53, "time": 10, "value": False},
                {"code": "doorbell", "dp_id": 54, "time": 20, "value": True},
            ]
        }
    }

    assert properties_by_code(payload)["doorbell"] == TuyaProperty(
        code="doorbell",
        value=True,
        timestamp_ms=20_000,
        dp_id=54,
    )
