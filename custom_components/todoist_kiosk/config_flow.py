"""Config flow for Todoist Kiosk."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TodoistAuthError, TodoistKioskApi, TodoistKioskError
from .const import CONF_API_TOKEN, DOMAIN


class TodoistKioskConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a Todoist personal API token."""

    VERSION = 1

    async def _async_validate(self, token: str) -> None:
        api = TodoistKioskApi(async_get_clientsession(self.hass), token)
        await api.validate_token()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle initial setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_API_TOKEN].strip()
            try:
                await self._async_validate(token)
            except TodoistAuthError:
                errors["base"] = "invalid_auth"
            except TodoistKioskError:
                errors["base"] = "cannot_connect"
            except Exception:  # Home Assistant reports unexpected setup bugs safely.
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="Todoist Kiosk", data={CONF_API_TOKEN: token}
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_TOKEN): vol.All(
                        str, vol.Length(min=1, max=512)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after Todoist rejects the token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and store a replacement token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_API_TOKEN].strip()
            try:
                await self._async_validate(token)
            except TodoistAuthError:
                errors["base"] = "invalid_auth"
            except TodoistKioskError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_API_TOKEN: token},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_TOKEN): vol.All(
                        str, vol.Length(min=1, max=512)
                    )
                }
            ),
            errors=errors,
        )
