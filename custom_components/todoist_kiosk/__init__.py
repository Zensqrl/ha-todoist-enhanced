"""Todoist Kiosk integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .const import CONF_API_TOKEN, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .api import TodoistKioskApi
    from .coordinator import TodoistMetadataCoordinator


@dataclass(slots=True)
class TodoistKioskRuntimeData:
    """Runtime objects for a configured Todoist account."""

    api: TodoistKioskApi
    coordinator: TodoistMetadataCoordinator
    entry: ConfigEntry


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration and its authenticated WebSocket interface."""
    from .websocket import async_register_websocket_commands

    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get("websocket_registered"):
        async_register_websocket_commands(hass)
        domain_data["websocket_registered"] = True
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Todoist Kiosk from a config entry."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .api import TodoistKioskApi
    from .coordinator import TodoistMetadataCoordinator

    session = async_get_clientsession(hass)
    api = TodoistKioskApi(session, entry.data[CONF_API_TOKEN])
    coordinator = TodoistMetadataCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    runtime = TodoistKioskRuntimeData(api=api, coordinator=coordinator, entry=entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    entry.runtime_data = runtime
    entry.async_on_unload(coordinator.async_add_listener(lambda: None))
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Todoist Kiosk config entry."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
