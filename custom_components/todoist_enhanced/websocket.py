"""Authenticated structured reads and admin-only task mutations."""

from __future__ import annotations

import probatio as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .api import TodoistAuthError, TodoistEnhancedError
from .const import DOMAIN

SELECTORS = ("project_id", "filter", "filter_id", "filter_name")
BASE_SCHEMA = {
    vol.Optional("entry_id"): str,
    vol.Optional("force_refresh", default=False): bool,
}
TASK_SCHEMA = {
    **BASE_SCHEMA,
    **{
        vol.Exclusive(key, "source"): vol.All(str, vol.Length(min=1, max=1024))
        for key in SELECTORS
    },
}


def get_runtime(hass, entry_id=None):
    runtimes = hass.data.get(DOMAIN, {})
    if entry_id is not None:
        return runtimes.get(entry_id)
    return next(iter(runtimes.values()), None) if len(runtimes) == 1 else None


def project_entity_mapping(hass, project_ids):
    """Resolve only the native integration's stable project-ID convention."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    mapping = {project_id: [] for project_id in project_ids}
    for entry in hass.config_entries.async_entries("todoist"):
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
            if entity.domain != "todo" or entity.platform != "todoist":
                continue
            for project_id in project_ids:
                if entity.unique_id == f"{entry.entry_id}-{project_id}":
                    mapping[project_id].append(entity.entity_id)
    return mapping


async def execute(hass, runtime, operation, msg):
    backend = runtime.backend
    force = msg.get("force_refresh", False)
    if operation == "tasks":
        result = await backend.tasks({k: msg[k] for k in SELECTORS if k in msg}, force)
    elif operation in ("catalogs", "sources", "filters", "labels", "refresh_metadata"):
        result = await backend.catalogs(force or operation == "refresh_metadata")
        if result["data"] is not None:
            projects = result["data"]["projects"]
            mapping = project_entity_mapping(hass, [p["id"] for p in projects])
            for project in projects:
                project["native_todo_entities"] = mapping[project["id"]]
                project["mapping_status"] = (
                    "matched" if mapping[project["id"]] else "unresolved"
                )
    elif operation == "complete_task":
        result = await backend.complete_task(msg["task_id"].strip())
    elif operation == "quick_add":
        result = await backend.quick_add(msg["text"].strip())
    else:
        raise ValueError("Unknown operation")
    errors = [result.get("error"), result.get("metadata", {}).get("error")]
    if any(e and e["code"] == "auth_failed" for e in errors):
        runtime.entry.async_start_reauth(hass)
    if operation in ("complete_task", "quick_add"):
        hass.bus.async_fire(
            f"{DOMAIN}_updated",
            {"entry_id": runtime.entry.entry_id, "refresh_required": True},
        )
    return result


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    for operation in (
        "tasks",
        "catalogs",
        "sources",
        "filters",
        "labels",
        "refresh_metadata",
        "complete_task",
        "quick_add",
    ):
        schema = dict(TASK_SCHEMA if operation == "tasks" else BASE_SCHEMA)
        if operation == "complete_task":
            schema[vol.Required("task_id")] = vol.All(str, vol.Length(min=1, max=128))
        if operation == "quick_add":
            schema[vol.Required("text")] = vol.All(str, vol.Length(min=1, max=2048))
        schema[vol.Required("type")] = f"{DOMAIN}/{operation}"

        async def handler(hass, connection, msg, operation=operation):
            if (
                operation in ("complete_task", "quick_add")
                and not connection.user.is_admin
            ):
                connection.send_error(
                    msg["id"], "unauthorized", "Task mutations require an administrator"
                )
                return
            runtime = get_runtime(hass, msg.get("entry_id"))
            if runtime is None:
                connection.send_error(
                    msg["id"],
                    "integration_not_loaded",
                    "Todoist Enhanced is not configured",
                )
                return
            try:
                if (
                    operation in ("complete_task", "quick_add")
                    and not msg.get("task_id", msg.get("text", "")).strip()
                ):
                    raise ValueError("Input cannot be blank")
                result = await execute(hass, runtime, operation, msg)
            except TodoistEnhancedError as err:
                if isinstance(err, TodoistAuthError):
                    runtime.entry.async_start_reauth(hass)
                connection.send_error(msg["id"], err.code, err.safe_message)
            except ValueError:
                connection.send_error(
                    msg["id"], "invalid_input", "Invalid or blank source/input"
                )
            else:
                connection.send_result(msg["id"], result)

        command = websocket_api.websocket_command(schema)(
            websocket_api.async_response(handler)
        )
        websocket_api.async_register_command(hass, command)
