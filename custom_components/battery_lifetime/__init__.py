"""The Battery Lifetime integration.

Single-instance integration whose ``async_setup_entry`` builds the
:class:`BatteryLifetimeStore`, the :class:`BatteryLifetimeCoordinator`,
registers the ``predict_at`` service, and forwards setup to all entity
platforms.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import BatteryLifetimeCoordinator
from .services import async_register_services, async_unregister_services
from .store import BatteryLifetimeStore

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    from .const import CONF_DEFAULT_PROFILE, DEFAULT_PROFILE

    store = BatteryLifetimeStore(hass)
    await store.async_load()
    options_default = entry.options.get(CONF_DEFAULT_PROFILE, DEFAULT_PROFILE)
    if store.default_profile != options_default:
        store.set_default_profile(options_default)
    coordinator = BatteryLifetimeCoordinator(hass, store=store)
    await coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "store": store,
    }

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    bucket = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if bucket is not None:
        coordinator: BatteryLifetimeCoordinator = bucket["coordinator"]
        await coordinator.async_shutdown()
    if not hass.data.get(DOMAIN):
        async_unregister_services(hass)
    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
