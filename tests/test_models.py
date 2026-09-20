"""Tests for the frontend task contract and saved-filter resolution."""

from __future__ import annotations

import unittest

from custom_components.todoist_enhanced.models import (
    MetadataSnapshot,
    TodoistFilter,
    TodoistProject,
    TodoistSection,
    normalize_task,
    resolve_saved_filter,
)


class ModelsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = MetadataSnapshot.build(
            [TodoistProject("p1", "Home")],
            [TodoistSection("s1", "Maintenance", "p1")],
            [TodoistFilter("f1", "Enhanced Upcoming", "today | overdue")],
        )

    def test_task_is_enriched_and_normalized(self) -> None:
        task = normalize_task(
            {
                "id": "t1",
                "content": "Change furnace filter",
                "project_id": "p1",
                "section_id": "s1",
                "labels": ["house"],
                "priority": 2,
                "due": {
                    "date": "2026-08-20T14:00:00Z",
                    "string": "Thursday",
                    "is_recurring": True,
                },
                "deadline": {"date": "2026-08-31"},
            },
            self.snapshot,
        )

        self.assertEqual(task["project_name"], "Home")
        self.assertEqual(task["section_name"], "Maintenance")
        self.assertEqual(task["due"]["date"], "2026-08-20")
        self.assertEqual(task["due"]["datetime"], "2026-08-20T14:00:00Z")
        self.assertTrue(task["due"]["is_recurring"])
        self.assertEqual(task["deadline"]["date"], "2026-08-31")

    def test_null_due_and_missing_metadata_are_safe(self) -> None:
        task = normalize_task(
            {
                "id": "t2",
                "content": "Unscheduled",
                "project_id": "missing",
                "section_id": "missing",
            },
            self.snapshot,
        )

        self.assertIsNone(task["due"])
        self.assertIsNone(task["deadline"])
        self.assertIsNone(task["project_name"])
        self.assertIsNone(task["section_name"])

    def test_deadline_without_due_is_preserved(self) -> None:
        task = normalize_task(
            {
                "id": "t3",
                "content": "Deadline only",
                "deadline": {"date": "2026-09-01"},
            },
            self.snapshot,
        )
        self.assertIsNone(task["due"])
        self.assertEqual(task["deadline"]["date"], "2026-09-01")

    def test_saved_filter_resolves_by_id_or_case_insensitive_name(self) -> None:
        self.assertEqual(
            resolve_saved_filter(self.snapshot, filter_id="f1").query, "today | overdue"
        )
        self.assertEqual(
            resolve_saved_filter(self.snapshot, filter_name="enhanced upcoming").id,
            "f1",
        )

    def test_missing_or_duplicate_saved_filter_is_rejected(self) -> None:
        with self.assertRaises(LookupError):
            resolve_saved_filter(self.snapshot, filter_name="Missing")

        duplicate_snapshot = MetadataSnapshot.build(
            [],
            [],
            [
                TodoistFilter("f1", "Same", "today"),
                TodoistFilter("f2", "same", "overdue"),
            ],
        )
        with self.assertRaisesRegex(LookupError, "ambiguous"):
            resolve_saved_filter(duplicate_snapshot, filter_name="Same")


if __name__ == "__main__":
    unittest.main()
