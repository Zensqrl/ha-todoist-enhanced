# Todoist Enhanced dashboard contract v1

This integration supplies facts to the Daily Decision Dashboard. It does not rank,
schedule, infer suitability from titles, create labels, or reserve calendar time.

## Read interfaces

Authenticated Home Assistant WebSocket:

```json
{"id":1,"type":"todoist_enhanced/tasks","force_refresh":true}
```

No selector means **all active tasks**, including undated, overdue and future tasks.
Use at most one of `project_id`, `filter`, `filter_id`, or `filter_name`. Saved filter
names are case-insensitive and must be unambiguous. Names/queries otherwise retain
their original content. Todoist evaluates filters; the integration has no parser.
The optional `entry_id` selects the HA config entry; omitted is allowed only when
exactly one account is loaded. One account is supported in this release.

`todoist_enhanced/catalogs` returns projects, sections, saved filters and personal
and shared label names. `sources`, `filters`, and `labels` are aliases returning
the **same catalog envelope**, not separate legacy card response shapes.
`refresh_metadata` forces a catalog refresh. All reads accept `force_refresh`.

Response-returning HA actions:

```yaml
action: todoist_enhanced.get_tasks
data:
  force_refresh: true
response_variable: task_snapshot
```

`get_catalogs` and `refresh` return the catalog envelope. These actions require a
response; scripts should supply `response_variable`. WebSocket errors for invalid
schemas, missing integration/entry, and invalid selectors occur outside the data
envelope. Never interpret an unsuccessful HA response as an empty list.

## Freshness and completeness

Every envelope includes `contract_version: 1`, opaque `account_id` (the HA config
entry ID), `planning_timezone`, `requested_at`, `attempted_at`, `fetched_at`,
`last_successful_fetch`, `outcome`, `data_source`, `stale`, `complete`,
`latest_attempt_complete`, and `error`.

- Times are UTC ISO-8601 strings. Unavailable times are null.
- `requested_at`: this read; `attempted_at`: latest attempted upstream retrieval.
- `fetched_at` / `last_successful_fetch`: when the returned snapshot was successfully
  retrieved. These do not advance when a cache is read or a retrieval fails.
- `outcome`: `success` or `error` for the latest attempted retrieval.
- `data_source`: `network`, `cache`, `retained` after failure, or `none`.
- `stale`: the returned data has expired or the latest retrieval failed.
- `complete`: returned snapshot completed all cursor pages. A retained older
  snapshot can still be complete. This does **not** imply freshness.
- `latest_attempt_complete`: false if the latest attempt failed, including a
  failure after some pages. Interrupted results never replace a complete cache.
- `error`: null or a sanitized code/message. Upstream error bodies are not echoed.
- Successful empty tasks: `tasks: []`, outcome success, complete true.
- Failed first retrieval: `tasks: null`, outcome error, complete false.

Task results include `scope` (selector, resolved query, explicit exclusions,
`truncated: false`), `pagination` (pages, duplicates removed, returned/excluded
counts), and `metadata` (catalog freshness envelope without its data).
`enrichment_complete` is false if catalogs are failed/stale or a referenced project
or section cannot be resolved. Raw task labels and IDs remain usable independently.
Consumers must inspect task **and metadata** status. Do not rank stale results as fresh.

Cursor traversal is capped at 1,000 pages as a safety guard. Reaching the guard,
repeated cursors, malformed results or later-page failures fail the attempt rather
than returning truncated success. Stable IDs deduplicate tasks. Todoist's cursor
API is not a transactional snapshot; simultaneous upstream edits can affect pages.

## Task fields

| Field | Meaning |
| --- | --- |
| `id` | Stable Todoist ID, string; never derive identity from title |
| `content` | Title |
| `description` | Original description; null if absent; empty string remains empty |
| `is_completed` | Boolean; the active endpoint establishes false if its flag is omitted |
| `project_id`, `project_name` | Stable ID and catalog name; unresolved name is null |
| `section_id`, `section_name`, `parent_id` | Optional hierarchy metadata |
| `labels` | Exact arbitrary attached names; null if the API omitted labels, [] if explicitly empty |
| `label_details` | Names plus personal label IDs where resolved; unresolved/shared IDs null |
| `priority` | Raw Todoist API value: 4 highest, 1 lowest; null if absent |
| `display_priority` | App convention: 1 highest, 4 lowest; `5 - priority`; null if unknown/invalid |
| `due` | Null or date object described below; current recurring occurrence |
| `deadline` | Separate date-only deadline object; null if absent |
| `duration` | Native `{amount, unit}` without conversion or label overrides; null if absent |
| `is_uncompletable` | API flag if provided; null if unspecified |
| `assignee_id` | API responsible/assignee ID, optional; no personal name lookup |
| `created_at`, `updated_at` | Original upstream timestamps when available |
| `url` | Upstream task URL when available; null otherwise |

Due objects expose `kind: date|datetime`, `date`, `datetime`, `timezone`, `string`
(Todoist recurrence/date expression), `is_recurring` (nullable), and `lang`.
Timed strings retain their original offset and supplied named timezone. A timed
value without either is unresolved; do not invent a UTC offset. Date-only values
are interpreted as dates in `planning_timezone`, never midnight appointments.
Deadline objects expose `kind: date`, `date`, `lang`. They remain distinct from due.

Missing duration is not zero. Missing recurrence/actionability flags are not false.
Raw duration and arbitrary labels are independent facts: conflict resolution and
suitability interpretation belong to the dashboard's explicit policy.

Completed, deleted, and explicitly API-identified uncompletable items are excluded
and counted. The current published API does not guarantee an uncompletable flag;
unflagged headers cannot reliably be identified. No title-based guessing is used.

## Catalogs and native entity mapping

Catalog `data` contains `projects`, `sections`, `filters`, `labels`,
`label_catalog_scope: personal_and_shared_labels`, and
`shared_label_ids_available: false`. Personal labels include unused labels.
Shared labels are retrieved using Todoist's shared-label endpoint, which returns
names rather than IDs. Exact duplicate names are merged; original case is retained.

Projects include `native_todo_entities` and `mapping_status: matched|unresolved`.
Mapping uses native Todoist registry unique IDs (`config_entry_id-project_id`),
never name matching. Unconfigured/unsupported native mappings yield an empty list
and unresolved status. This is a read-only compatibility adapter, not a stable HA
public API guarantee. No native entities, calendars, or config entries are modified.

Todoist calendar entries are due-date projections and must not automatically block
calendar availability, especially all-day task events.

## Updates, credentials and mutations

All-active tasks refresh in HA every 60 seconds even without a card. Task cache TTL
is 60 seconds; catalog TTL is 30 minutes. Forced task reads also refresh catalogs.
The bounded in-memory cache holds at most 64 source snapshots and is cleared by a
reload/restart. Concurrent identical reads share work. Rate-limit backoff applies
across sources and cannot be bypassed with force refresh.

`todoist_enhanced_updated` HA events announce backend refreshes/mutations using an
entry ID and outcome/refresh-required indicator, without task data. Future cards can
subscribe through HA's event API and re-read. These events do not guarantee that
Todoist changed; this integration polls rather than receiving Todoist webhooks.

Authenticated HA users can read the configured account's data. There is no per-user
project isolation. WebSocket mutations require an administrator. HA actions enforce
admin for user-originated calls; trusted automations without a user context can run.
Configuration remains admin-managed. Do not share HA access with users who must not
see this account's tasks. Credentials stay in the config entry, never in responses.

`todoist_enhanced/complete_task` (`task_id`) and `/quick_add` (`text`) are writes;
equivalent response-returning actions exist. Completion uses `/close`, never delete.
Quick Add is not redirected by the currently displayed source. Neither mutation is
automatically retried. After ambiguous timeout/error, refresh and reconcile in
Todoist before a human retries; completed history reconciliation is not implemented.
Mutations invalidate caches even on errors. No offline queue is implemented.

## Sanitized illustrative payload (not live acceptance evidence)

```json
{
  "contract_version": 1,
  "account_id": "example-entry",
  "planning_timezone": "America/New_York",
  "outcome": "success",
  "data_source": "network",
  "stale": false,
  "complete": true,
  "latest_attempt_complete": true,
  "fetched_at": "2026-09-20T12:00:00+00:00",
  "last_successful_fetch": "2026-09-20T12:00:00+00:00",
  "error": null,
  "tasks": [{
    "id": "example-task",
    "content": "Example task",
    "description": null,
    "project_id": "example-project",
    "project_name": "Home",
    "labels": ["Any existing label"],
    "label_details": [{"name": "Any existing label", "id": null}],
    "priority": 4,
    "display_priority": 1,
    "is_completed": false,
    "due": null,
    "deadline": null,
    "duration": null
  }]
}
```

Example abbreviated for readability; timestamps, scope, pagination, metadata, and
optional fields described above are part of actual responses.
