"""Behavioral fixtures for dashboard data integrity and recovery."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from custom_components.todoist_enhanced.api import (
    TodoistRateLimitError,
    TodoistUnavailableError,
)
from custom_components.todoist_enhanced.backend import TaskBackend
from custom_components.todoist_enhanced.models import TodoistFilter, TodoistProject


@pytest.fixture
def api():
    api = AsyncMock()
    api.get_projects.return_value = [TodoistProject("p", "Home")]
    api.get_sections.return_value = []
    api.get_saved_filters.return_value = [
        TodoistFilter("f", "Upcoming", "today | overdue")
    ]
    api.get_labels.return_value = [
        {"id": "l", "name": "arbitrary label"},
        {"id": "unused", "name": "Unused"},
    ]
    api.get_shared_labels.return_value = ["Shared label"]
    api.get_tasks.return_value = [
        {
            "id": "t",
            "content": "Undated",
            "project_id": "p",
            "labels": ["arbitrary label"],
            "priority": 4,
        }
    ]
    return api


@pytest.fixture
def backend(api):
    return TaskBackend(api, "account", "America/New_York")


async def test_labels_priority_missing_and_unused_catalog(backend):
    result = await backend.tasks()
    task = result["tasks"][0]
    assert task["labels"] == ["arbitrary label"]
    assert task["label_details"] == [{"id": "l", "name": "arbitrary label"}]
    assert task["display_priority"] == 1
    assert task["due"] is task["duration"] is task["deadline"] is None
    assert result["complete"] and not result["stale"]
    assert result["scope"]["kind"] == "all_active"
    assert (await backend.catalogs())["data"]["labels"][1]["name"] == "Unused"


async def test_cache_failure_retention_and_recovery(backend, api):
    good = await backend.tasks()
    cached = await backend.tasks()
    assert cached["data_source"] == "cache"
    api.get_tasks.side_effect = TodoistUnavailableError("Unavailable")
    failed = await backend.tasks(force=True)
    assert failed["tasks"] == good["tasks"]
    assert failed["fetched_at"] == good["fetched_at"]
    assert failed["stale"] and failed["data_source"] == "retained"
    assert not failed["latest_attempt_complete"]
    api.get_tasks.side_effect = None
    api.get_tasks.return_value = []
    empty = await backend.tasks(force=True)
    assert empty["tasks"] == [] and empty["outcome"] == "success" and not empty["stale"]


async def test_failed_first_read_is_not_empty(backend, api):
    api.get_tasks.side_effect = TodoistUnavailableError("Unavailable")
    result = await backend.tasks()
    assert result["tasks"] is None
    assert not result["complete"] and result["outcome"] == "error"


async def test_date_recurrence_duration_and_offset(backend, api):
    api.get_tasks.return_value = [
        {
            "id": "date",
            "content": "Date",
            "due": {"date": "2026-01-01", "is_recurring": False},
        },
        {
            "id": "time",
            "content": "Timed",
            "due": {
                "date": "2026-10-01T09:00:00-04:00",
                "timezone": "America/New_York",
                "is_recurring": True,
                "string": "every day",
            },
            "duration": {"amount": 30, "unit": "minute"},
            "deadline": {"date": "2026-10-04"},
        },
        {"id": "header", "content": "Header", "is_uncompletable": True},
    ]
    result = await backend.tasks()
    assert len(result["tasks"]) == 2
    date, timed = result["tasks"]
    assert date["due"]["kind"] == "date" and date["due"]["datetime"] is None
    assert timed["due"]["datetime"].endswith("-04:00")
    assert timed["due"]["is_recurring"] and timed["due"]["string"] == "every day"
    assert timed["duration"]["amount"] == 30
    assert timed["deadline"]["date"] == "2026-10-04"
    assert result["pagination"]["excluded"] == 1


async def test_concurrent_reads_share_network(backend, api):
    gate = asyncio.Event()

    async def tasks():
        await gate.wait()
        return []

    api.get_tasks.side_effect = tasks
    first = asyncio.create_task(backend.tasks(force=True))
    await asyncio.sleep(0)
    second = asyncio.create_task(backend.tasks(force=True))
    await asyncio.sleep(0)
    gate.set()
    await asyncio.gather(first, second)
    assert api.get_tasks.await_count == 1


async def test_mutation_invalidates_and_is_never_retried(backend, api):
    await backend.tasks()
    api.close_task.side_effect = TodoistUnavailableError("Ambiguous timeout")
    with pytest.raises(TodoistUnavailableError):
        await backend.complete_task("t")
    api.close_task.assert_awaited_once_with("t")
    await backend.tasks()
    assert api.get_tasks.await_count == 2


async def test_metadata_failure_does_not_hide_raw_task_data(backend, api):
    api.get_labels.side_effect = TodoistUnavailableError("Unavailable")
    result = await backend.tasks()
    assert result["tasks"][0]["labels"] == ["arbitrary label"]
    assert result["tasks"][0]["project_name"] is None
    assert not result["enrichment_complete"]
    assert result["metadata"]["outcome"] == "error"


async def test_rate_limit_backoff_blocks_requests_even_forced(backend, api):
    api.get_tasks.side_effect = TodoistRateLimitError("Rate limited", 120)
    await backend.tasks()
    result = await backend.tasks(force=True)
    assert result["error"]["code"] == "rate_limited"
    assert api.get_tasks.await_count == 1


async def test_saved_and_raw_filter_routing(backend, api):
    api.get_tasks_by_filter.return_value = []
    result = await backend.tasks({"filter_id": "f"})
    api.get_tasks_by_filter.assert_awaited_once_with("today | overdue")
    assert result["scope"]["resolved_query"] == "today | overdue"
    missing = await backend.tasks({"filter_id": "missing"})
    assert missing["tasks"] is None and missing["error"]["code"] == "filter_not_found"
