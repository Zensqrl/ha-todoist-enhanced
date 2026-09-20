"""Dashboard facts and shared operations; deliberately independent of HA."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from .api import TodoistEnhancedError, TodoistProtocolError, TodoistRateLimitError
from .models import MetadataSnapshot, normalize_task, resolve_saved_filter


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskBackend:
    """Bounded shared cache with atomic snapshots and explicit failed attempts."""

    def __init__(self, api: Any, account_id: str, planning_timezone: str) -> None:
        self.api = api
        self.account_id = account_id
        self.planning_timezone = planning_timezone
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = asyncio.Lock()
        self._retry_until = 0.0
        self._generation = 0

    def invalidate(self) -> None:
        self._generation += 1
        for item in self._cache.values():
            item["expires"] = 0

    async def _read(
        self,
        key: str,
        loader: Any,
        force: bool,
        ttl: int,
        request_clock: float | None = None,
    ) -> dict:
        requested = utcnow()
        started = request_clock if request_clock is not None else monotonic()
        async with self._lock:
            cached = self._cache.get(key)
            if cached:
                self._cache.move_to_end(key)
            # Concurrent forced reads share the fetch already performed for them.
            if (
                cached
                and cached["expires"] > started
                and (not force or cached["attempt_clock"] >= started)
            ):
                return self._envelope(cached, requested, "cache")
            if monotonic() < self._retry_until:
                error = {
                    "code": "rate_limited",
                    "message": "Todoist rate limit backoff is active",
                }
                item = dict(cached or self._empty())
                item.update(attempted_at=requested, error=error)
                return self._envelope(
                    item, requested, "retained" if item["data"] is not None else "none"
                )
            generation = self._generation
            try:
                data = await loader()
            except TodoistEnhancedError as err:
                if isinstance(err, TodoistRateLimitError):
                    self._retry_until = monotonic() + max(1, err.retry_after or 60)
                item = dict(cached or self._empty())
                item.update(
                    attempted_at=utcnow(),
                    attempt_clock=monotonic(),
                    error={"code": err.code, "message": err.safe_message},
                    expires=0,
                )
            else:
                fetched_at = utcnow()
                item = {
                    "data": data,
                    "fetched_at": fetched_at,
                    "attempted_at": fetched_at,
                    "attempt_clock": monotonic(),
                    "error": None,
                    "expires": monotonic() + ttl
                    if generation == self._generation
                    else 0,
                }
            self._cache[key] = item
            while len(self._cache) > 64:
                self._cache.popitem(last=False)
            return self._envelope(
                item,
                requested,
                "network"
                if item["error"] is None
                else "retained"
                if item["data"] is not None
                else "none",
            )

    @staticmethod
    def _empty() -> dict:
        return {"data": None, "fetched_at": None, "expires": 0}

    def _envelope(self, item: dict, requested: str, source: str) -> dict:
        return {
            "contract_version": 1,
            "account_id": self.account_id,
            "planning_timezone": self.planning_timezone,
            "requested_at": requested,
            "attempted_at": item["attempted_at"],
            "fetched_at": item["fetched_at"],
            "last_successful_fetch": item["fetched_at"],
            "outcome": "error" if item["error"] else "success",
            "data_source": source,
            "stale": bool(item["error"] or item["expires"] <= monotonic()),
            "complete": item["data"] is not None,
            "latest_attempt_complete": item["error"] is None,
            "error": deepcopy(item["error"]),
            "data": deepcopy(item["data"]),
        }

    async def catalogs(self, force: bool = False) -> dict:
        async def load() -> dict:
            # Sequential operations respect a single account's request budget.
            projects = await self.api.get_projects()
            sections = await self.api.get_sections()
            filters = await self.api.get_saved_filters()
            raw_labels = await self.api.get_labels()
            shared_labels = await self.api.get_shared_labels()
            labels = []
            for label in raw_labels:
                if not isinstance(label.get("name"), str):
                    raise TodoistProtocolError("Invalid label catalog")
                labels.append({"id": str(label["id"]), "name": label["name"]})
            known_names = {label["name"] for label in labels}
            labels.extend(
                {"id": None, "name": name}
                for name in shared_labels
                if name not in known_names
            )
            return {
                "projects": [asdict(p) for p in projects],
                "sections": [asdict(s) for s in sections],
                "filters": [asdict(f) for f in filters],
                "labels": labels,
                "label_catalog_scope": "personal_and_shared_labels",
                "shared_label_ids_available": False,
            }

        return await self._read("catalogs", load, force, 1800)

    async def tasks(self, selector: dict | None = None, force: bool = False) -> dict:
        from .models import TodoistFilter, TodoistProject, TodoistSection

        request_clock = monotonic()
        selector = selector or {}
        if len(selector) > 1 or any(
            k not in ("project_id", "filter", "filter_id", "filter_name")
            for k in selector
        ):
            raise ValueError("At most one source selector is allowed")
        if any(not isinstance(v, str) or not v.strip() for v in selector.values()):
            raise ValueError("Source selectors cannot be blank")
        metadata = await self.catalogs(force)
        catalog = metadata["data"] or {
            "projects": [],
            "sections": [],
            "filters": [],
            "labels": [],
        }
        snapshot = MetadataSnapshot.build(
            [TodoistProject(**p) for p in catalog["projects"]],
            [TodoistSection(**s) for s in catalog["sections"]],
            [TodoistFilter(**f) for f in catalog["filters"]],
            catalog["labels"],
        )
        query = selector.get("filter")
        if "filter_id" in selector or "filter_name" in selector:
            if metadata["outcome"] != "success" or metadata["stale"]:
                return self._unavailable(selector, metadata, "catalog_unavailable")
            try:
                query = resolve_saved_filter(snapshot, **selector).query
            except LookupError:
                return self._unavailable(selector, metadata, "filter_not_found")
        key = repr(sorted(selector.items())) + repr(query)

        async def load() -> dict:
            if query is not None:
                values = await self.api.get_tasks_by_filter(query)
            elif "project_id" in selector:
                values = await self.api.get_tasks_by_project(selector["project_id"])
            else:
                values = await self.api.get_tasks()
            for value in values:
                if not isinstance(value.get("content"), str) or not value.get("id"):
                    raise TodoistProtocolError("Invalid task identity or title")
                labels = value.get("labels")
                if labels is not None and (
                    not isinstance(labels, list)
                    or any(not isinstance(name, str) for name in labels)
                ):
                    raise TodoistProtocolError("Invalid task labels")
            return {
                "items": list(values),
                "pages": getattr(values, "pages", None),
                "duplicates_removed": getattr(values, "duplicates", 0),
            }

        result = await self._read(key, load, force, 60, request_clock)
        payload = result.pop("data")
        result.update(
            scope={
                "kind": "all_active" if not selector else next(iter(selector)),
                **selector,
                "resolved_query": query,
                "exclusions": ["completed", "deleted", "api_identified_uncompletable"],
                "truncated": False,
            },
            metadata={k: v for k, v in metadata.items() if k != "data"},
            tasks=None,
            pagination=None,
            enrichment_complete=False,
        )
        if payload is not None:
            tasks = [
                normalize_task(t, snapshot)
                for t in payload["items"]
                if not t.get("checked")
                and not t.get("is_completed")
                and not t.get("is_deleted")
                and not t.get("is_uncompletable")
            ]
            # The active endpoint establishes active status even if checked is absent.
            for task in tasks:
                if task["is_completed"] is None:
                    task["is_completed"] = False
            result["tasks"] = tasks
            result["pagination"] = {
                "pages": payload["pages"],
                "duplicates_removed": payload["duplicates_removed"],
                "returned": len(tasks),
                "excluded": len(payload["items"]) - len(tasks),
            }
            result["enrichment_complete"] = (
                metadata["outcome"] == "success"
                and not metadata["stale"]
                and all(t["project_name"] is not None for t in tasks)
                and all(
                    not t["section_id"] or t["section_name"] is not None for t in tasks
                )
            )
        return result

    def _unavailable(self, selector: dict, metadata: dict, code: str) -> dict:
        now = utcnow()
        result = self._envelope(
            {
                **self._empty(),
                "attempted_at": now,
                "error": {"code": code, "message": "Unable to resolve saved filter"},
            },
            now,
            "none",
        )
        result.pop("data")
        result.update(
            tasks=None,
            scope=selector,
            metadata={k: v for k, v in metadata.items() if k != "data"},
            pagination=None,
            enrichment_complete=False,
        )
        return result

    async def complete_task(self, task_id: str) -> dict:
        # Never automatically replay a completion: recurring tasks can advance twice.
        try:
            await self.api.close_task(task_id)
        finally:
            self.invalidate()
        return {"success": True, "refresh_required": True}

    async def quick_add(self, text: str) -> dict:
        try:
            raw = await self.api.quick_add_task(text)
        finally:
            self.invalidate()
        return {
            "success": True,
            "task_id": str(raw["id"]) if raw.get("id") else None,
            "refresh_required": True,
        }
