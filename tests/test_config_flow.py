"""Tests for the config flow + options flow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import PERCENTAGE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.battery_lifetime.const import (
    CONF_DEFAULT_PROFILE,
    DOMAIN,
    PROFILE_ALKALINE,
    PROFILE_LITHIUM,
)
from custom_components.battery_lifetime.coordinator import (
    BatteryLifetimeCoordinator,
)
from custom_components.battery_lifetime.store import BatteryLifetimeStore

UTC = timezone.utc


async def test_first_add_succeeds(hass: Any) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Battery Lifetime"
    assert result["options"][CONF_DEFAULT_PROFILE] == PROFILE_LITHIUM


async def test_second_add_aborts(hass: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_DEFAULT_PROFILE: PROFILE_LITHIUM},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow_change_default_profile(hass: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, options={CONF_DEFAULT_PROFILE: PROFILE_LITHIUM}
    )
    entry.add_to_hass(hass)

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coord}

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "default_profile"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "default_profile"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_DEFAULT_PROFILE: PROFILE_ALKALINE},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEFAULT_PROFILE] == PROFILE_ALKALINE
    assert store.default_profile == PROFILE_ALKALINE
    await coord.async_shutdown()


async def test_options_flow_default_profile_does_not_retroactively_change(
    hass: Any,
) -> None:
    """Existing batteries keep their profile when default_profile flips."""
    entry = MockConfigEntry(
        domain=DOMAIN, options={CONF_DEFAULT_PROFILE: PROFILE_LITHIUM}
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="sensor",
        platform="demo",
        unique_id="uid-foo",
        suggested_object_id="foo_battery",
        original_device_class=SensorDeviceClass.BATTERY,
        unit_of_measurement=PERCENTAGE,
    )
    hass.states.async_set("sensor.foo_battery", "84", {})
    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coord}

    assert coord.records["uid-foo"].profile_id == PROFILE_LITHIUM
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "default_profile"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_DEFAULT_PROFILE: PROFILE_ALKALINE},
    )
    assert coord.records["uid-foo"].profile_id == PROFILE_LITHIUM
    await coord.async_shutdown()


async def test_options_flow_bulk_edit_persists(hass: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, options={CONF_DEFAULT_PROFILE: PROFILE_LITHIUM}
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="sensor",
        platform="demo",
        unique_id="uid-foo",
        suggested_object_id="foo_battery",
        original_device_class=SensorDeviceClass.BATTERY,
        unit_of_measurement=PERCENTAGE,
    )
    hass.states.async_set("sensor.foo_battery", "84", {})
    store = BatteryLifetimeStore(hass)
    await store.async_load()
    coord = BatteryLifetimeCoordinator(hass, store=store)
    await coord.async_setup()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coord}

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "bulk_overview"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "bulk_overview"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"battery": "uid-foo"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "edit_battery"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "tracking_enabled": False,
            "profile_lithium": False,
            "threshold_override": 25,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert coord.records["uid-foo"].tracking_enabled is False
    assert coord.records["uid-foo"].profile_id == PROFILE_ALKALINE
    assert coord.records["uid-foo"].threshold_override == 25
    await coord.async_shutdown()
