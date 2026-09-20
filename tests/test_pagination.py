"""Fault injection for complete retrieval, shared labels and safe failures."""

import pytest

from custom_components.todoist_enhanced.api import (
    TodoistEnhancedApi,
    TodoistProtocolError,
    TodoistUnavailableError,
)

from .test_api import FakeResponse, FakeSession


async def test_duplicate_tasks_and_page_count():
    api = TodoistEnhancedApi(
        FakeSession(
            [
                FakeResponse(200, {"results": [{"id": "one"}], "next_cursor": "two"}),
                FakeResponse(
                    200,
                    {"results": [{"id": "one"}, {"id": "two"}], "next_cursor": None},
                ),
            ]
        ),
        "secret",
    )
    tasks = await api.get_tasks()
    assert [t["id"] for t in tasks] == ["one", "two"]
    assert tasks.pages == 2 and tasks.duplicates == 1


async def test_second_page_failure_never_returns_partial_success():
    api = TodoistEnhancedApi(
        FakeSession(
            [
                FakeResponse(200, {"results": [{"id": "one"}], "next_cursor": "two"}),
                FakeResponse(503, {}),
            ]
        ),
        "secret",
    )
    with pytest.raises(TodoistUnavailableError):
        await api.get_tasks()


async def test_cursor_loop_and_invalid_item_fail():
    for pages in (
        [FakeResponse(200, {"results": [{"id": "one"}], "next_cursor": "loop"})] * 2,
        [FakeResponse(200, {"results": [{"content": "no ID"}], "next_cursor": None})],
    ):
        with pytest.raises(TodoistProtocolError):
            await TodoistEnhancedApi(FakeSession(pages), "secret").get_tasks()


async def test_shared_label_names_paginate_without_fabricating_ids():
    api = TodoistEnhancedApi(
        FakeSession(
            [
                FakeResponse(
                    200,
                    {"results": ["arbitrary", "Untouched Case"], "next_cursor": "two"},
                ),
                FakeResponse(
                    200, {"results": ["arbitrary", "unused"], "next_cursor": None}
                ),
            ]
        ),
        "secret",
    )
    assert await api.get_shared_labels() == ["arbitrary", "Untouched Case", "unused"]
