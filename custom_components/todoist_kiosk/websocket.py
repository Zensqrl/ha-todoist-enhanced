"""Authenticated Home Assistant WebSocket commands for Todoist Kiosk."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .api import TodoistAuthError, TodoistKioskError
from .const import (
    DOMAIN,
    FILTER_MAX_LENGTH,
    QUICK_ADD_MAX_LENGTH,
    TASK_ID_MAX_LENGTH,
    WS_COMPLETE_TASK,
    WS_FILTERS,
    WS_QUICK_ADD,
    WS_REFRESH_METADATA,
    WS_SOURCES,
    WS_TASKS,
)
from .models import normalize_task, resolve_saved_filter


def _get_runtime(hass: HomeAssistant) -> Any | None:
    """Return the single supported account runtime."""
    for key, value in hass.data.get(DOMAIN, {}).items():
        if key != "websocket_registered":
            return value
    return None


def _send_integration_not_loaded(connection: Any, msg: dict[str, Any]) -> None:
    connection.send_error(
        msg["id"], "integration_not_loaded", "Todoist Kiosk is not configured"
    )


def _send_api_error(
    hass: HomeAssistant,
    runtime: Any,
    connection: Any,
    msg: dict[str, Any],
    err: TodoistKioskError,
) -> None:
    if isinstance(err, TodoistAuthError):
        runtime.entry.async_start_reauth(hass)
    connection.send_error(msg["id"], err.code, err.safe_message)


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_TASKS,
        vol.Exclusive("filter", "selector"): vol.All(
            str, vol.Length(min=1, max=FILTER_MAX_LENGTH)
        ),
        vol.Exclusive("filter_id", "selector"): vol.All(
            str, vol.Length(min=1, max=TASK_ID_MAX_LENGTH)
        ),
        vol.Exclusive("filter_name", "selector"): vol.All(
            str, vol.Length(min=1, max=256)
        ),
        vol.Exclusive("project_id", "selector"): vol.All(
            str, vol.Length(min=1, max=TASK_ID_MAX_LENGTH)
        ),
    }
)
@websocket_api.async_response
async def websocket_tasks(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Return normalized tasks matching a project or Todoist filter."""
    runtime = _get_runtime(hass)
    if runtime is None:
        _send_integration_not_loaded(connection, msg)
        return
    selectors = ("filter", "filter_id", "filter_name", "project_id")
    selector_count = sum(key in msg for key in selectors)
    if selector_count != 1:
        connection.send_error(
            msg["id"],
            "invalid_filter",
            "Exactly one task source selector is required",
        )
        return

    snapshot = runtime.coordinator.data
    if snapshot is None:
        _send_integration_not_loaded(connection, msg)
        return

    try:
        if "project_id" in msg:
            project_id = msg["project_id"].strip()
            if not project_id or project_id not in snapshot.projects_by_id:
                connection.send_error(
                    msg["id"],
                    "project_not_found",
                    "Todoist project was not found",
                )
                return
            raw_tasks = await runtime.api.get_tasks_by_project(project_id)
        else:
            if "filter" in msg:
                query = msg["filter"].strip()
                if not query:
                    connection.send_error(
                        msg["id"], "invalid_filter", "Filter cannot be blank"
                    )
                    return
            else:
                try:
                    query = resolve_saved_filter(
                        snapshot,
                        filter_id=msg.get("filter_id"),
                        filter_name=msg.get("filter_name"),
                    ).query
                except LookupError as err:
                    connection.send_error(msg["id"], "filter_not_found", str(err))
                    return

            raw_tasks = await runtime.api.get_tasks_by_filter(query)
        tasks = [normalize_task(task, snapshot) for task in raw_tasks]
    except TodoistKioskError as err:
        _send_api_error(hass, runtime, connection, msg, err)
        return

    connection.send_result(msg["id"], {"tasks": tasks})


@websocket_api.websocket_command({vol.Required("type"): WS_SOURCES})
@websocket_api.async_response
async def websocket_sources(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Return active projects and saved filters as a stable source catalog."""
    runtime = _get_runtime(hass)
    if runtime is None or runtime.coordinator.data is None:
        _send_integration_not_loaded(connection, msg)
        return

    snapshot = runtime.coordinator.data
    projects = sorted(
        snapshot.projects_by_id.values(),
        key=lambda project: (project.name.casefold(), project.id),
    )
    filters = sorted(
        snapshot.filters_by_id.values(),
        key=lambda saved_filter: (saved_filter.name.casefold(), saved_filter.id),
    )
    sources = [
        {"kind": "project", "id": project.id, "name": project.name}
        for project in projects
    ]
    sources.extend(
        {"kind": "saved_filter", "id": saved_filter.id, "name": saved_filter.name}
        for saved_filter in filters
    )
    connection.send_result(msg["id"], {"sources": sources})


@websocket_api.websocket_command({vol.Required("type"): WS_FILTERS})
@websocket_api.async_response
async def websocket_filters(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Return saved Todoist filters without exposing credentials."""
    runtime = _get_runtime(hass)
    if runtime is None or runtime.coordinator.data is None:
        _send_integration_not_loaded(connection, msg)
        return
    filters = sorted(
        runtime.coordinator.data.filters_by_id.values(),
        key=lambda saved_filter: saved_filter.name.casefold(),
    )
    connection.send_result(
        msg["id"], {"filters": [saved_filter.as_dict() for saved_filter in filters]}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_COMPLETE_TASK,
        vol.Required("task_id"): vol.All(
            str, vol.Length(min=1, max=TASK_ID_MAX_LENGTH)
        ),
    }
)
@websocket_api.async_response
async def websocket_complete_task(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Complete a task by immutable Todoist task ID."""
    runtime = _get_runtime(hass)
    if runtime is None:
        _send_integration_not_loaded(connection, msg)
        return
    task_id = msg["task_id"].strip()
    if not task_id:
        connection.send_error(msg["id"], "task_not_found", "Task ID cannot be blank")
        return
    try:
        await runtime.api.close_task(task_id)
    except TodoistKioskError as err:
        _send_api_error(hass, runtime, connection, msg, err)
        return
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_QUICK_ADD,
        vol.Required("text"): vol.All(
            str, vol.Length(min=1, max=QUICK_ADD_MAX_LENGTH)
        ),
    }
)
@websocket_api.async_response
async def websocket_quick_add(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Create a task through Todoist's natural-language Quick Add endpoint."""
    runtime = _get_runtime(hass)
    if runtime is None:
        _send_integration_not_loaded(connection, msg)
        return
    text = msg["text"].strip()
    if not text:
        connection.send_error(
            msg["id"], "quick_add_failed", "Quick Add text cannot be blank"
        )
        return
    try:
        result = await runtime.api.quick_add_task(text)
    except TodoistKioskError as err:
        _send_api_error(hass, runtime, connection, msg, err)
        return
    connection.send_result(msg["id"], {"success": True, "result": dict(result)})


@websocket_api.websocket_command({vol.Required("type"): WS_REFRESH_METADATA})
@websocket_api.async_response
async def websocket_refresh_metadata(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Explicitly refresh cached projects, sections, and filters."""
    runtime = _get_runtime(hass)
    if runtime is None:
        _send_integration_not_loaded(connection, msg)
        return
    await runtime.coordinator.async_request_refresh()
    if not runtime.coordinator.last_update_success:
        connection.send_error(
            msg["id"], "todoist_unavailable", "Unable to refresh Todoist metadata"
        )
        return
    connection.send_result(msg["id"], {"success": True})


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register all Todoist Kiosk commands once during integration setup."""
    websocket_api.async_register_command(hass, websocket_tasks)
    websocket_api.async_register_command(hass, websocket_filters)
    websocket_api.async_register_command(hass, websocket_sources)
    websocket_api.async_register_command(hass, websocket_complete_task)
    websocket_api.async_register_command(hass, websocket_quick_add)
    websocket_api.async_register_command(hass, websocket_refresh_metadata)
