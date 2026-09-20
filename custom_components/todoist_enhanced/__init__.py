"""Todoist Enhanced: dashboard facts without replacing native Todoist entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .api import TodoistAuthError, TodoistEnhancedApi, TodoistEnhancedError
from .backend import TaskBackend
from .const import CONF_API_TOKEN, DOMAIN


@dataclass
class TodoistEnhancedRuntimeData:
    backend: TaskBackend
    entry: ConfigEntry


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    from .services import async_register_services
    from .websocket import async_register_websocket_commands

    hass.data.setdefault(DOMAIN, {})
    async_register_websocket_commands(hass)
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = TodoistEnhancedApi(async_get_clientsession(hass), entry.data[CONF_API_TOKEN])
    try:
        await api.validate_token()
    except TodoistAuthError as err:
        raise ConfigEntryAuthFailed(err.safe_message) from err
    except TodoistEnhancedError as err:
        raise ConfigEntryNotReady(err.safe_message) from err
    backend = TaskBackend(api, entry.entry_id, hass.config.time_zone)
    runtime = TodoistEnhancedRuntimeData(backend, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    entry.runtime_data = runtime

    async def refresh(_now=None):
        result = await backend.tasks()
        errors = [result.get("error"), result.get("metadata", {}).get("error")]
        if any(e and e["code"] == "auth_failed" for e in errors):
            entry.async_start_reauth(hass)
        hass.bus.async_fire(
            f"{DOMAIN}_updated",
            {"entry_id": entry.entry_id, "outcome": result["outcome"]},
        )

    @callback
    def scheduled_refresh(_now):
        entry.async_create_background_task(hass, refresh(), "todoist_enhanced_refresh")

    entry.async_on_unload(
        async_track_time_interval(hass, scheduled_refresh, timedelta(seconds=60))
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    entry.async_create_background_task(
        hass, refresh(), "todoist_enhanced_initial_refresh"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
