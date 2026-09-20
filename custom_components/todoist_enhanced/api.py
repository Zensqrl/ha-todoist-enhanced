"""Async client for the Todoist API v1."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import quote

from .const import API_BASE_URL, API_PAGE_LIMIT, API_REQUEST_TIMEOUT
from .models import TodoistFilter, TodoistProject, TodoistSection


class AsyncHttpSession(Protocol):
    """The subset of aiohttp.ClientSession used by this integration."""

    def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


class TodoistEnhancedError(Exception):
    """Base class for safe, frontend-facing Todoist errors."""

    code = "unknown_error"

    def __init__(self, message: str = "Todoist request failed") -> None:
        super().__init__(message)
        self.safe_message = message


class TodoistAuthError(TodoistEnhancedError):
    code = "auth_failed"


class TodoistInvalidFilterError(TodoistEnhancedError):
    code = "invalid_filter"


class TodoistNotFoundError(TodoistEnhancedError):
    code = "task_not_found"


class TodoistProjectNotFoundError(TodoistEnhancedError):
    code = "project_not_found"


class TodoistQuickAddError(TodoistEnhancedError):
    code = "quick_add_failed"


class TodoistRateLimitError(TodoistEnhancedError):
    code = "rate_limited"

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TodoistUnavailableError(TodoistEnhancedError):
    code = "todoist_unavailable"


class TodoistProtocolError(TodoistEnhancedError):
    """Todoist returned a successful but unexpected response."""


class PaginatedItems(list):
    """Complete cursor traversal with per-request provenance."""

    pages: int = 0
    duplicates: int = 0


def _safe_error_message(payload: Any, fallback: str) -> str:
    # Upstream messages can echo submitted content. Never expose them.
    return fallback


class TodoistEnhancedApi:
    """Small typed wrapper around only the endpoints needed by the kiosk."""

    def __init__(
        self,
        session: AsyncHttpSession,
        token: str,
        *,
        base_url: str = API_BASE_URL,
    ) -> None:
        self._session = session
        self._token = token
        self._base_url = base_url.rstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        bad_request_error: type[TodoistEnhancedError] = TodoistEnhancedError,
        not_found_error: type[TodoistEnhancedError] = TodoistNotFoundError,
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                params=dict(params) if params else None,
                data=dict(data) if data else None,
                json=dict(json_body) if json_body else None,
                timeout=API_REQUEST_TIMEOUT,
            ) as response:
                text = await response.text()
                payload: Any = None
                if text:
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        payload = None

                if response.status in (401, 403):
                    raise TodoistAuthError("Todoist rejected the API token")
                if response.status == 400:
                    raise bad_request_error(
                        _safe_error_message(payload, "Todoist rejected the request")
                    )
                if response.status == 404:
                    raise not_found_error(
                        _safe_error_message(payload, "Todoist resource was not found")
                    )
                if response.status == 429:
                    retry_after: int | None = None
                    raw_retry = response.headers.get("Retry-After")
                    if raw_retry and raw_retry.isdigit():
                        retry_after = int(raw_retry)
                    elif isinstance(payload, Mapping):
                        extra = payload.get("error_extra")
                        if isinstance(extra, Mapping) and isinstance(
                            extra.get("retry_after"), int
                        ):
                            retry_after = extra["retry_after"]
                    raise TodoistRateLimitError(
                        "Todoist rate limit reached; try again later", retry_after
                    )
                if response.status >= 500:
                    raise TodoistUnavailableError("Todoist is temporarily unavailable")
                if response.status < 200 or response.status >= 300:
                    raise TodoistEnhancedError(
                        _safe_error_message(payload, "Todoist request failed")
                    )
                return payload
        except TodoistEnhancedError:
            raise
        except Exception as err:
            # Do not include the request or token in the exception message.
            raise TodoistUnavailableError("Unable to communicate with Todoist") from err

    async def _get_paginated(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        bad_request_error: type[TodoistEnhancedError] = TodoistEnhancedError,
        not_found_error: type[TodoistEnhancedError] = TodoistNotFoundError,
        strings: bool = False,
    ) -> list[Mapping[str, Any]]:
        results = PaginatedItems()
        ids: set[str] = set()
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            page_params = dict(params or {})
            page_params["limit"] = API_PAGE_LIMIT
            if cursor:
                page_params["cursor"] = cursor

            payload = await self._request(
                "GET",
                path,
                params=page_params,
                bad_request_error=bad_request_error,
                not_found_error=not_found_error,
            )
            if not isinstance(payload, Mapping) or not isinstance(
                payload.get("results"), list
            ):
                raise TodoistProtocolError("Todoist returned an unexpected response")

            results.pages += 1
            for item in payload["results"]:
                if strings and isinstance(item, str):
                    item_id = item
                elif (
                    not strings
                    and isinstance(item, Mapping)
                    and item.get("id") is not None
                ):
                    item_id = str(item["id"])
                else:
                    raise TodoistProtocolError("Invalid item in Todoist response")
                if item_id in ids:
                    results.duplicates += 1
                    continue
                ids.add(item_id)
                results.append(item)
            next_cursor = payload.get("next_cursor")
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise TodoistProtocolError("Invalid pagination cursor")
            if not next_cursor:
                return results

            cursor = str(next_cursor)
            if cursor in seen_cursors:
                raise TodoistProtocolError("Todoist pagination did not advance")
            seen_cursors.add(cursor)
            if results.pages >= 1000:
                raise TodoistProtocolError("Todoist pagination safety limit reached")

    async def get_tasks(self) -> list[Mapping[str, Any]]:
        """All active tasks, including undated and future tasks."""
        return await self._get_paginated("/tasks")

    async def get_labels(self) -> list[Mapping[str, Any]]:
        return await self._get_paginated("/labels")

    async def get_shared_labels(self) -> list[str]:
        return await self._get_paginated("/labels/shared", strings=True)

    async def validate_token(self) -> None:
        """Make a small authenticated request used by the config flow."""
        await self._request("GET", "/projects", params={"limit": 1})

    async def get_tasks_by_filter(self, query: str) -> list[Mapping[str, Any]]:
        return await self._get_paginated(
            "/tasks/filter",
            params={"query": query},
            bad_request_error=TodoistInvalidFilterError,
        )

    async def get_tasks_by_project(self, project_id: str) -> list[Mapping[str, Any]]:
        """Return every active task in a project across all cursor pages."""
        return await self._get_paginated(
            "/tasks",
            params={"project_id": project_id},
            bad_request_error=TodoistProjectNotFoundError,
            not_found_error=TodoistProjectNotFoundError,
        )

    async def get_projects(self) -> list[TodoistProject]:
        values = await self._get_paginated("/projects")
        if any(not isinstance(value.get("name"), str) for value in values):
            raise TodoistProtocolError("Invalid project metadata")
        return [TodoistProject.from_api(value) for value in values]

    async def get_sections(self) -> list[TodoistSection]:
        values = await self._get_paginated("/sections")
        if any(not isinstance(value.get("name"), str) for value in values):
            raise TodoistProtocolError("Invalid section metadata")
        return [TodoistSection.from_api(value) for value in values]

    async def get_saved_filters(self) -> list[TodoistFilter]:
        payload = await self._request(
            "POST",
            "/sync",
            data={"sync_token": "*", "resource_types": json.dumps(["filters"])},
        )
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("filters"), list
        ):
            raise TodoistProtocolError("Todoist returned an unexpected response")

        for value in payload["filters"]:
            if not isinstance(value, Mapping):
                raise TodoistProtocolError("Invalid saved filter metadata")
            if not value.get("is_deleted") and (
                value.get("id") is None
                or not isinstance(value.get("name"), str)
                or not isinstance(value.get("query"), str)
                or not value["query"]
            ):
                raise TodoistProtocolError("Invalid saved filter metadata")
        return [
            TodoistFilter.from_api(value)
            for value in payload["filters"]
            if isinstance(value, Mapping)
            and not value.get("is_deleted", False)
            and value.get("id") is not None
            and value.get("query")
        ]

    async def close_task(self, task_id: str) -> None:
        await self._request("POST", f"/tasks/{quote(task_id, safe='')}/close")

    async def quick_add_task(self, text: str) -> Mapping[str, Any]:
        payload = await self._request(
            "POST",
            "/tasks/quick",
            json_body={"text": text, "meta": True},
            bad_request_error=TodoistQuickAddError,
        )
        if not isinstance(payload, Mapping) or payload.get("id") is None:
            raise TodoistProtocolError("Todoist returned an unexpected response")
        return payload
