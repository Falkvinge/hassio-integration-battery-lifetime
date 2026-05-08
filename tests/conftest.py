"""Pytest configuration shared across the Battery Lifetime test suite.

We auto-enable ``pytest_homeassistant_custom_component``'s fixtures (which give
us ``hass``, ``hass_storage``, etc.) for the integration-level tests, and
provide a few helpers used by the pure-logic tests.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

pytest_plugins = ("pytest_homeassistant_custom_component",)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None, None, None]:
    """Enable HA's custom-integrations loader for every test."""
    yield
