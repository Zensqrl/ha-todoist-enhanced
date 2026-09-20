"""Diagnostics intentionally contain no credentials, task text or identifiers."""

from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass, entry):
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    return {
        "contract_version": 1,
        "loaded": runtime is not None,
        "cached_sources": len(runtime.backend._cache) if runtime else 0,
    }
