"""Metadata coordinator for Todoist Kiosk."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TodoistAuthError,
    TodoistKioskApi,
    TodoistKioskError,
    TodoistRateLimitError,
)
from .const import DOMAIN, METADATA_UPDATE_INTERVAL
from .models import MetadataSnapshot

_LOGGER = logging.getLogger(__name__)


class TodoistMetadataCoordinator(DataUpdateCoordinator[MetadataSnapshot]):
    """Refresh projects, sections, and saved filters at a conservative cadence."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: TodoistKioskApi
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}_metadata",
            update_interval=METADATA_UPDATE_INTERVAL,
        )
        self.api = api

    async def _async_update_data(self) -> MetadataSnapshot:
        try:
            projects, sections, filters = await asyncio.gather(
                self.api.get_projects(),
                self.api.get_sections(),
                self.api.get_saved_filters(),
            )
        except TodoistAuthError as err:
            raise ConfigEntryAuthFailed(err.safe_message) from err
        except TodoistRateLimitError as err:
            raise UpdateFailed(
                err.safe_message, retry_after=err.retry_after
            ) from err
        except TodoistKioskError as err:
            raise UpdateFailed(err.safe_message) from err

        return MetadataSnapshot.build(projects, sections, filters)
