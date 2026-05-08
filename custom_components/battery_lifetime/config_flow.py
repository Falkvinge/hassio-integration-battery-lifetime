"""Config flow + options flow for the Battery Lifetime integration.

A user adds the integration once; subsequent attempts abort with the
``single_instance_allowed`` reason. The options flow has two screens:

* The default-profile selector (``alkaline`` / ``lithium``), used as the
  starting profile for newly discovered batteries.
* A bulk overview that lists every tracked battery so the user can flip
  ``tracking_enabled`` / ``profile_lithium`` / ``threshold_override`` from
  one place. Per-battery edits in the bulk view persist through the
  coordinator to the same store the per-entity controls write to.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    ALL_PROFILES,
    CONF_DEFAULT_PROFILE,
    DEFAULT_PROFILE,
    DOMAIN,
    PROFILE_ALKALINE,
    PROFILE_LITHIUM,
)
from .coordinator import BatteryLifetimeCoordinator

_PROFILE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=list(ALL_PROFILES),
        translation_key="default_profile",
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)


class BatteryLifetimeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-instance config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Mapping[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=vol.Schema({}))
        await self.async_set_unique_id(DOMAIN)
        return self.async_create_entry(
            title="Battery Lifetime",
            data={},
            options={CONF_DEFAULT_PROFILE: DEFAULT_PROFILE},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> BatteryLifetimeOptionsFlow:
        return BatteryLifetimeOptionsFlow(config_entry)


class BatteryLifetimeOptionsFlow(OptionsFlow):
    """Options flow with default-profile + bulk-overview screens."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._selected_unique_id: str | None = None

    @property
    def _coordinator(self) -> BatteryLifetimeCoordinator | None:
        bucket = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
        if bucket is None:
            return None
        return bucket.get("coordinator")

    async def async_step_init(
        self, user_input: Mapping[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["default_profile", "bulk_overview"],
        )

    async def async_step_default_profile(
        self, user_input: Mapping[str, Any] | None = None
    ) -> ConfigFlowResult:
        coordinator = self._coordinator
        current = self._config_entry.options.get(
            CONF_DEFAULT_PROFILE, DEFAULT_PROFILE
        )
        if user_input is not None:
            new_profile = user_input[CONF_DEFAULT_PROFILE]
            new_options = {
                **self._config_entry.options,
                CONF_DEFAULT_PROFILE: new_profile,
            }
            if coordinator is not None:
                coordinator.store.set_default_profile(new_profile)
            return self.async_create_entry(title="", data=new_options)
        return self.async_show_form(
            step_id="default_profile",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEFAULT_PROFILE, default=current
                    ): _PROFILE_SELECTOR
                }
            ),
        )

    async def async_step_bulk_overview(
        self, user_input: Mapping[str, Any] | None = None
    ) -> ConfigFlowResult:
        coordinator = self._coordinator
        if coordinator is None or not coordinator.records:
            return self.async_abort(reason="no_batteries")
        if user_input is not None:
            self._selected_unique_id = user_input["battery"]
            return await self.async_step_edit_battery()
        options = sorted(
            (
                (record.unique_id, record.entity_id)
                for record in coordinator.iter_active_records()
            ),
            key=lambda item: item[1],
        )
        return self.async_show_form(
            step_id="bulk_overview",
            data_schema=vol.Schema(
                {
                    vol.Required("battery"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=unique_id, label=entity_id
                                )
                                for unique_id, entity_id in options
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_edit_battery(
        self, user_input: Mapping[str, Any] | None = None
    ) -> ConfigFlowResult:
        coordinator = self._coordinator
        if coordinator is None or self._selected_unique_id is None:
            return self.async_abort(reason="no_batteries")
        record = coordinator.records.get(self._selected_unique_id)
        if record is None:
            return self.async_abort(reason="no_batteries")
        if user_input is not None:
            await coordinator.set_tracking_enabled(
                self._selected_unique_id, bool(user_input["tracking_enabled"])
            )
            await coordinator.set_profile(
                self._selected_unique_id,
                PROFILE_LITHIUM if user_input["profile_lithium"] else PROFILE_ALKALINE,
            )
            override_raw = user_input.get("threshold_override")
            override = (
                None
                if override_raw in (None, "", "null")
                else float(override_raw)
            )
            await coordinator.set_threshold_override(
                self._selected_unique_id, override
            )
            return self.async_create_entry(
                title="", data=dict(self._config_entry.options)
            )

        return self.async_show_form(
            step_id="edit_battery",
            description_placeholders={
                "entity_id": record.entity_id,
                "replaced_on": (
                    record.replaced_on.isoformat()
                    if record.replaced_on
                    else "unknown"
                ),
            },
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "tracking_enabled", default=record.tracking_enabled
                    ): selector.BooleanSelector(),
                    vol.Required(
                        "profile_lithium",
                        default=record.profile_id == PROFILE_LITHIUM,
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        "threshold_override",
                        default=record.threshold_override,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=100,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
