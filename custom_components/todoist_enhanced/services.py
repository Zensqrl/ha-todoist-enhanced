"""Response-returning HA actions using the same backend as WebSocket reads."""

import probatio as vol
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError, Unauthorized

from .api import TodoistAuthError, TodoistEnhancedError
from .const import DOMAIN
from .websocket import BASE_SCHEMA, TASK_SCHEMA, execute, get_runtime


def async_register_services(hass):
    for name, operation in (
        ("get_tasks", "tasks"),
        ("get_catalogs", "catalogs"),
        ("refresh", "refresh_metadata"),
        ("complete_task", "complete_task"),
        ("quick_add", "quick_add"),
    ):
        schema = dict(TASK_SCHEMA if operation == "tasks" else BASE_SCHEMA)
        if operation == "complete_task":
            schema[vol.Required("task_id")] = vol.All(str, vol.Length(min=1, max=128))
        if operation == "quick_add":
            schema[vol.Required("text")] = vol.All(str, vol.Length(min=1, max=2048))

        async def handler(call, operation=operation):
            if operation in ("complete_task", "quick_add") and call.context.user_id:
                user = await hass.auth.async_get_user(call.context.user_id)
                if user is None or not user.is_admin:
                    raise Unauthorized()
            runtime = get_runtime(hass, call.data.get("entry_id"))
            if runtime is None:
                raise HomeAssistantError("Todoist Enhanced is not configured")
            try:
                if (
                    operation in ("complete_task", "quick_add")
                    and not call.data.get("task_id", call.data.get("text", "")).strip()
                ):
                    raise ValueError("Blank input")
                return await execute(hass, runtime, operation, call.data)
            except TodoistAuthError as err:
                runtime.entry.async_start_reauth(hass)
                raise HomeAssistantError("Todoist authentication failed") from err
            except (TodoistEnhancedError, ValueError) as err:
                raise HomeAssistantError(
                    "Todoist operation failed; refresh before retrying a mutation"
                ) from err

        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            schema=vol.Schema(schema),
            supports_response=SupportsResponse.ONLY,
        )
