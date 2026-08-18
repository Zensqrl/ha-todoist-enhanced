"""Focused tests for the WebSocket command handlers.

The small stubs keep these tests dependency-free; Home Assistant's own schema layer is
also exercised by hassfest/real-instance validation.
"""

from __future__ import annotations

import sys
import types
import unittest
from typing import Any


registered_commands: list[Any] = []


def _identity_decorator(*args: Any, **kwargs: Any):
    def decorate(function: Any) -> Any:
        return function

    return decorate


voluptuous = types.ModuleType("voluptuous")
voluptuous.Required = lambda key: key
voluptuous.Exclusive = lambda key, group: key
voluptuous.Length = lambda **kwargs: (lambda value: value)
voluptuous.All = lambda *validators: validators[-1]
sys.modules.setdefault("voluptuous", voluptuous)

homeassistant = types.ModuleType("homeassistant")
homeassistant.__path__ = []
components = types.ModuleType("homeassistant.components")
components.__path__ = []
websocket_api = types.ModuleType("homeassistant.components.websocket_api")
websocket_api.websocket_command = _identity_decorator
websocket_api.async_response = lambda function: function
websocket_api.async_register_command = lambda hass, command: registered_commands.append(command)
components.websocket_api = websocket_api
core = types.ModuleType("homeassistant.core")
core.HomeAssistant = object
sys.modules.setdefault("homeassistant", homeassistant)
sys.modules.setdefault("homeassistant.components", components)
sys.modules.setdefault("homeassistant.components.websocket_api", websocket_api)
sys.modules.setdefault("homeassistant.core", core)

from custom_components.todoist_kiosk.api import TodoistInvalidFilterError
from custom_components.todoist_kiosk.const import DOMAIN
from custom_components.todoist_kiosk.models import (
    MetadataSnapshot,
    TodoistFilter,
    TodoistProject,
)
from custom_components.todoist_kiosk.websocket import (
    async_register_websocket_commands,
    websocket_complete_task,
    websocket_filters,
    websocket_quick_add,
    websocket_tasks,
)


class FakeConnection:
    def __init__(self) -> None:
        self.result: tuple[int, Any] | None = None
        self.error: tuple[int, str, str] | None = None

    def send_result(self, message_id: int, result: Any) -> None:
        self.result = (message_id, result)

    def send_error(self, message_id: int, code: str, message: str) -> None:
        self.error = (message_id, code, message)


class FakeApi:
    def __init__(self) -> None:
        self.query: str | None = None
        self.closed_id: str | None = None
        self.quick_text: str | None = None
        self.error: Exception | None = None

    async def get_tasks_by_filter(self, query: str) -> list[dict[str, Any]]:
        if self.error:
            raise self.error
        self.query = query
        return [{"id": "t1", "content": "Task", "project_id": "p1"}]

    async def close_task(self, task_id: str) -> None:
        self.closed_id = task_id

    async def quick_add_task(self, text: str) -> dict[str, str]:
        self.quick_text = text
        return {"id": "created"}


class FakeCoordinator:
    def __init__(self, data: MetadataSnapshot) -> None:
        self.data = data
        self.last_update_success = True

    async def async_request_refresh(self) -> None:
        return None


class FakeHass:
    def __init__(self, runtime: Any) -> None:
        self.data = {DOMAIN: {"entry": runtime, "websocket_registered": True}}


class WebsocketTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        snapshot = MetadataSnapshot.build(
            [TodoistProject("p1", "Home")],
            [],
            [TodoistFilter("f1", "Kiosk", "today | overdue")],
        )
        self.api = FakeApi()
        runtime = types.SimpleNamespace(
            api=self.api, coordinator=FakeCoordinator(snapshot)
        )
        self.hass = FakeHass(runtime)

    async def test_raw_filter_returns_normalized_tasks(self) -> None:
        connection = FakeConnection()
        await websocket_tasks(
            self.hass, connection, {"id": 1, "type": "todoist_kiosk/tasks", "filter": "today"}
        )
        self.assertEqual(self.api.query, "today")
        self.assertEqual(connection.result[1]["tasks"][0]["project_name"], "Home")

    async def test_saved_filter_resolves_and_missing_selector_is_rejected(self) -> None:
        connection = FakeConnection()
        await websocket_tasks(
            self.hass,
            connection,
            {"id": 2, "type": "todoist_kiosk/tasks", "filter_id": "f1"},
        )
        self.assertEqual(self.api.query, "today | overdue")

        missing = FakeConnection()
        await websocket_tasks(
            self.hass, missing, {"id": 3, "type": "todoist_kiosk/tasks"}
        )
        self.assertEqual(missing.error[1], "invalid_filter")

    async def test_api_error_code_is_stable(self) -> None:
        self.api.error = TodoistInvalidFilterError("Invalid query")
        connection = FakeConnection()
        await websocket_tasks(
            self.hass, connection, {"id": 4, "type": "todoist_kiosk/tasks", "filter": "("}
        )
        self.assertEqual(connection.error, (4, "invalid_filter", "Invalid query"))

    async def test_mutations_use_task_id_and_quick_add_text(self) -> None:
        complete = FakeConnection()
        await websocket_complete_task(
            self.hass,
            complete,
            {"id": 5, "type": "todoist_kiosk/complete_task", "task_id": "t1"},
        )
        self.assertEqual(self.api.closed_id, "t1")
        self.assertTrue(complete.result[1]["success"])

        quick = FakeConnection()
        await websocket_quick_add(
            self.hass,
            quick,
            {
                "id": 6,
                "type": "todoist_kiosk/quick_add",
                "text": "Buy filter tomorrow #Home",
            },
        )
        self.assertEqual(self.api.quick_text, "Buy filter tomorrow #Home")
        self.assertEqual(quick.result[1]["result"]["id"], "created")

    async def test_saved_filters_and_registration(self) -> None:
        connection = FakeConnection()
        await websocket_filters(
            self.hass, connection, {"id": 7, "type": "todoist_kiosk/filters"}
        )
        self.assertEqual(connection.result[1]["filters"][0]["id"], "f1")

        registered_commands.clear()
        async_register_websocket_commands(self.hass)
        self.assertEqual(len(registered_commands), 5)


if __name__ == "__main__":
    unittest.main()
