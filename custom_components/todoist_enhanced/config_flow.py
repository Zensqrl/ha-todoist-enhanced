"""Config flow for Todoist Enhanced."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import probatio as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TodoistAuthError, TodoistEnhancedApi, TodoistEnhancedError
from .const import CONF_API_TOKEN, DOMAIN


class TodoistEnhancedConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a Todoist personal API token."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return TodoistEnhancedOptionsFlow()

    async def _async_validate(self, token: str) -> None:
        api = TodoistEnhancedApi(async_get_clientsession(self.hass), token)
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
            except TodoistEnhancedError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - never expose credentials in setup errors
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="Todoist Enhanced", data={CONF_API_TOKEN: token}
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_API_TOKEN): vol.All(str, vol.Length(min=1, max=512))}
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
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
            except TodoistEnhancedError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - never expose credentials in setup errors
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_API_TOKEN: token},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_API_TOKEN): vol.All(str, vol.Length(min=1, max=512))}
            ),
            errors=errors,
        )


class TodoistEnhancedOptionsFlow(config_entries.OptionsFlow):
    """Allow existing installations to override the HA timezone."""

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            timezone = user_input.get("default_task_timezone", "").strip()
            try:
                if timezone:
                    ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, ValueError):
                errors["default_task_timezone"] = "invalid_timezone"
            else:
                return self.async_create_entry(
                    title="", data={"default_task_timezone": timezone}
                )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "default_task_timezone",
                        default=self.config_entry.options.get(
                            "default_task_timezone", ""
                        ),
                    ): str
                }
            ),
            errors=errors,
        )
