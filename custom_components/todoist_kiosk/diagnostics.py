"""Diagnostics support for Todoist Kiosk."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_TOKEN, DOMAIN


TO_REDACT = {CONF_API_TOKEN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return useful metadata counts with the API token redacted."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    snapshot = runtime.coordinator.data if runtime else None
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "metadata": {
            "projects": len(snapshot.projects_by_id) if snapshot else 0,
            "sections": len(snapshot.sections_by_id) if snapshot else 0,
            "saved_filters": len(snapshot.filters_by_id) if snapshot else 0,
            "last_update_success": (
                runtime.coordinator.last_update_success if runtime else False
            ),
        },
    }
