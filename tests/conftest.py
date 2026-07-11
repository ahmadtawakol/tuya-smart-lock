"""Shared test configuration for the Tuya Smart Lock integration."""

from collections.abc import Generator
from typing import Any

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: Any,
) -> Generator[None]:
    """Allow Home Assistant to load this custom integration in every test."""
    yield
