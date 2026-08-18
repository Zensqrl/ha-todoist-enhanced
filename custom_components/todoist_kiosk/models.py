"""Stable data models exposed by Todoist Kiosk."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


def _string_or_none(value: Any) -> str | None:
    """Return a string value without manufacturing the string 'None'."""
    return str(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class TodoistProject:
    """Small project representation used by the metadata cache."""

    id: str
    name: str

    @classmethod
    def from_api(cls, value: Mapping[str, Any]) -> TodoistProject:
        return cls(id=str(value["id"]), name=str(value.get("name") or ""))


@dataclass(frozen=True, slots=True)
class TodoistSection:
    """Small section representation used by the metadata cache."""

    id: str
    name: str
    project_id: str | None

    @classmethod
    def from_api(cls, value: Mapping[str, Any]) -> TodoistSection:
        return cls(
            id=str(value["id"]),
            name=str(value.get("name") or ""),
            project_id=_string_or_none(value.get("project_id")),
        )


@dataclass(frozen=True, slots=True)
class TodoistFilter:
    """Saved Todoist filter."""

    id: str
    name: str
    query: str

    @classmethod
    def from_api(cls, value: Mapping[str, Any]) -> TodoistFilter:
        return cls(
            id=str(value["id"]),
            name=str(value.get("name") or ""),
            query=str(value.get("query") or ""),
        )

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MetadataSnapshot:
    """Metadata that changes less frequently than task query results."""

    projects_by_id: dict[str, TodoistProject]
    sections_by_id: dict[str, TodoistSection]
    filters_by_id: dict[str, TodoistFilter]
    filter_ids_by_name: dict[str, tuple[str, ...]]

    @classmethod
    def build(
        cls,
        projects: list[TodoistProject],
        sections: list[TodoistSection],
        filters: list[TodoistFilter],
    ) -> MetadataSnapshot:
        ids_by_name: dict[str, list[str]] = {}
        for saved_filter in filters:
            ids_by_name.setdefault(saved_filter.name.casefold(), []).append(saved_filter.id)

        return cls(
            projects_by_id={project.id: project for project in projects},
            sections_by_id={section.id: section for section in sections},
            filters_by_id={saved_filter.id: saved_filter for saved_filter in filters},
            filter_ids_by_name={
                name: tuple(filter_ids) for name, filter_ids in ids_by_name.items()
            },
        )


def resolve_saved_filter(
    snapshot: MetadataSnapshot,
    *,
    filter_id: str | None = None,
    filter_name: str | None = None,
) -> TodoistFilter:
    """Resolve a saved filter, refusing to guess between duplicate names."""
    if filter_id is not None:
        saved_filter = snapshot.filters_by_id.get(filter_id.strip())
        if saved_filter is None:
            raise LookupError("Saved Todoist filter was not found")
        return saved_filter

    if filter_name is None:
        raise LookupError("A saved Todoist filter selector is required")

    filter_ids = snapshot.filter_ids_by_name.get(filter_name.strip().casefold(), ())
    if not filter_ids:
        raise LookupError("Saved Todoist filter was not found")
    if len(filter_ids) > 1:
        raise LookupError("Saved filter name is ambiguous; configure filter_id")
    return snapshot.filters_by_id[filter_ids[0]]


def _normalize_due(value: Any) -> dict[str, Any] | None:
    """Normalize both current and older Todoist due object variants."""
    if not isinstance(value, Mapping):
        return None

    raw_date = _string_or_none(value.get("date"))
    raw_datetime = _string_or_none(value.get("datetime"))
    if raw_datetime is None and raw_date and "T" in raw_date:
        raw_datetime = raw_date
        raw_date = raw_date[:10]

    return {
        "date": raw_date,
        "datetime": raw_datetime,
        "string": _string_or_none(value.get("string")),
        "is_recurring": bool(value.get("is_recurring", False)),
        "lang": _string_or_none(value.get("lang")),
    }


def _normalize_deadline(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        "date": _string_or_none(value.get("date")),
        "lang": _string_or_none(value.get("lang")),
    }


def _normalize_duration(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        "amount": value.get("amount"),
        "unit": _string_or_none(value.get("unit")),
    }


def normalize_task(
    value: Mapping[str, Any], metadata: MetadataSnapshot
) -> dict[str, Any]:
    """Convert a Todoist task into the card's versioned, stable contract."""
    task_id = str(value["id"])
    project_id = _string_or_none(value.get("project_id"))
    section_id = _string_or_none(value.get("section_id"))
    project = metadata.projects_by_id.get(project_id or "")
    section = metadata.sections_by_id.get(section_id or "")

    labels = value.get("labels")
    if not isinstance(labels, list):
        labels = []

    return {
        "id": task_id,
        "content": str(value.get("content") or ""),
        "description": str(value.get("description") or ""),
        "project_id": project_id,
        "project_name": project.name if project else None,
        "section_id": section_id,
        "section_name": section.name if section else None,
        "parent_id": _string_or_none(value.get("parent_id")),
        "labels": [str(label) for label in labels],
        "priority": value.get("priority"),
        "due": _normalize_due(value.get("due")),
        "deadline": _normalize_deadline(value.get("deadline")),
        "duration": _normalize_duration(value.get("duration")),
        "is_completed": bool(value.get("checked", False)),
        "url": _string_or_none(value.get("url")),
    }
