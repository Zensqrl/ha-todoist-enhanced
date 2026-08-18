"""Unit tests for the Todoist API client."""

from __future__ import annotations

import json
import unittest
from typing import Any

from custom_components.todoist_kiosk.api import (
    TodoistAuthError,
    TodoistInvalidFilterError,
    TodoistKioskApi,
    TodoistNotFoundError,
    TodoistQuickAddError,
    TodoistRateLimitError,
    TodoistUnavailableError,
)


class FakeResponse:
    def __init__(
        self, status: int, payload: Any = None, headers: dict[str, str] | None = None
    ) -> None:
        self.status = status
        self._text = payload if isinstance(payload, str) else json.dumps(payload)
        self.headers = headers or {}

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def text(self) -> str:
        return self._text


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TodoistKioskApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_filtered_tasks_follow_all_cursor_pages(self) -> None:
        session = FakeSession(
            [
                FakeResponse(200, {"results": [{"id": "one"}], "next_cursor": "c2"}),
                FakeResponse(200, {"results": [{"id": "two"}], "next_cursor": None}),
            ]
        )
        api = TodoistKioskApi(session, "secret")
        query = (
            "(due before: first day | deadline before: first day) & "
            "(!#Daily Checklist | today)"
        )

        tasks = await api.get_tasks_by_filter(query)

        self.assertEqual([task["id"] for task in tasks], ["one", "two"])
        self.assertEqual(session.requests[0][2]["params"]["limit"], 200)
        self.assertEqual(session.requests[0][2]["params"]["query"], query)
        self.assertNotIn("cursor", session.requests[0][2]["params"])
        self.assertEqual(session.requests[1][2]["params"]["cursor"], "c2")
        self.assertEqual(
            session.requests[0][2]["headers"]["Authorization"], "Bearer secret"
        )

    async def test_projects_and_sections_are_paginated_and_typed(self) -> None:
        session = FakeSession(
            [
                FakeResponse(200, {"results": [{"id": "p1", "name": "Home"}]}),
                FakeResponse(
                    200,
                    {
                        "results": [
                            {"id": "s1", "name": "Maintenance", "project_id": "p1"}
                        ]
                    },
                ),
            ]
        )
        api = TodoistKioskApi(session, "secret")

        projects = await api.get_projects()
        sections = await api.get_sections()

        self.assertEqual((projects[0].id, projects[0].name), ("p1", "Home"))
        self.assertEqual(
            (sections[0].id, sections[0].project_id), ("s1", "p1")
        )

    async def test_saved_filters_ignore_deleted_values(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    200,
                    {
                        "filters": [
                            {"id": "f1", "name": "Kiosk", "query": "today"},
                            {
                                "id": "f2",
                                "name": "Old",
                                "query": "overdue",
                                "is_deleted": True,
                            },
                        ]
                    },
                )
            ]
        )
        api = TodoistKioskApi(session, "secret")

        filters = await api.get_saved_filters()

        self.assertEqual([saved_filter.id for saved_filter in filters], ["f1"])
        request_data = session.requests[0][2]["data"]
        self.assertEqual(json.loads(request_data["resource_types"]), ["filters"])

    async def test_invalid_filter_maps_400(self) -> None:
        api = TodoistKioskApi(
            FakeSession([FakeResponse(400, {"error": "Invalid query"})]), "secret"
        )
        with self.assertRaisesRegex(TodoistInvalidFilterError, "Invalid query"):
            await api.get_tasks_by_filter("(")

    async def test_auth_errors_are_distinct(self) -> None:
        for status in (401, 403):
            with self.subTest(status=status):
                api = TodoistKioskApi(FakeSession([FakeResponse(status, {})]), "secret")
                with self.assertRaises(TodoistAuthError):
                    await api.validate_token()

    async def test_rate_limit_preserves_retry_after(self) -> None:
        api = TodoistKioskApi(
            FakeSession([FakeResponse(429, {}, {"Retry-After": "17"})]), "secret"
        )
        with self.assertRaises(TodoistRateLimitError) as raised:
            await api.get_projects()
        self.assertEqual(raised.exception.retry_after, 17)

    async def test_server_and_network_errors_are_unavailable(self) -> None:
        for response in (FakeResponse(503, {}), OSError("offline")):
            with self.subTest(response=response):
                api = TodoistKioskApi(FakeSession([response]), "secret")
                with self.assertRaises(TodoistUnavailableError):
                    await api.get_projects()

    async def test_close_task_uses_encoded_id_and_no_delete(self) -> None:
        session = FakeSession([FakeResponse(200, None)])
        api = TodoistKioskApi(session, "secret")

        await api.close_task("task/id")

        method, url, _ = session.requests[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/tasks/task%2Fid/close"))

    async def test_missing_task_maps_404(self) -> None:
        api = TodoistKioskApi(FakeSession([FakeResponse(404, {})]), "secret")
        with self.assertRaises(TodoistNotFoundError):
            await api.close_task("gone")

    async def test_quick_add_sends_natural_language_and_meta(self) -> None:
        session = FakeSession([FakeResponse(200, {"id": "new-task"})])
        api = TodoistKioskApi(session, "secret")

        result = await api.quick_add_task("Buy filter tomorrow #Home p2")

        self.assertEqual(result["id"], "new-task")
        self.assertEqual(
            session.requests[0][2]["json"],
            {"text": "Buy filter tomorrow #Home p2", "meta": True},
        )

    async def test_quick_add_maps_400(self) -> None:
        api = TodoistKioskApi(FakeSession([FakeResponse(400, {})]), "secret")
        with self.assertRaises(TodoistQuickAddError):
            await api.quick_add_task("bad")


if __name__ == "__main__":
    unittest.main()
