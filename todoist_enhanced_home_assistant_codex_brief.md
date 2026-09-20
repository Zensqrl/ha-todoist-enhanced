# Todoist Enhanced for Home Assistant — Codex Implementation Brief

**Status:** Historical initial specification; superseded by README.md and docs/data-contract.md for the Daily Decision Dashboard helper release.  
**Prepared:** 2026-08-18  
**Primary goal:** Build a focused Todoist experience inside a Home Assistant dashboard/kiosk without attempting to reproduce the full Todoist application.

---

## 1. Mission

Create a Home Assistant custom integration plus a Lovelace custom card that allows a Home Assistant kiosk user to:

1. Display Todoist tasks using **Todoist's native filter syntax**, including complex filters.
2. Display richer task information than Home Assistant's standard `todo` abstraction currently exposes.
3. Mark tasks complete.
4. Add tasks quickly.
5. Keep Todoist credentials and direct Todoist API traffic on the Home Assistant backend.
6. Keep the frontend focused, fast, touch-friendly, and suitable for a household kiosk.

The first concrete filter that must work is:

```text
(due before: first day | deadline before: first day) & (!#Daily Checklist | today)
```

This filter already exists in Todoist and represents the desired behavior:

> Show tasks due/deadlined before the first day of next month, excluding the `Daily Checklist` project unless a task is due today.

The integration should rely on Todoist to evaluate this query. **Do not recreate Todoist's filter parser in Home Assistant or JavaScript.**

---

## 2. Recommended Architecture

Use this architecture:

```text
┌────────────────────────┐
│      Todoist API       │
│                        │
│ Filters / Tasks /      │
│ Projects / Sections    │
└───────────┬────────────┘
            │ HTTPS
            │ Bearer token
            ▼
┌────────────────────────┐
│ Home Assistant custom  │
│ integration            │
│                        │
│ custom_components/     │
│ todoist_enhanced/         │
│                        │
│ - credentials          │
│ - API client           │
│ - filter execution     │
│ - metadata cache       │
│ - task mutations       │
│ - WebSocket commands   │
└───────────┬────────────┘
            │ Home Assistant
            │ WebSocket API
            ▼
┌────────────────────────┐
│ Lovelace custom card   │
│                        │
│ todoist-enhanced-card     │
│                        │
│ - render tasks         │
│ - user interaction     │
│ - add task             │
│ - complete task        │
│ - refresh              │
└────────────────────────┘
```

### Architectural rule

**The browser/card must not call `api.todoist.com` directly.**

All Todoist traffic must originate from the Home Assistant backend.

Reasons:

- The Todoist API token never needs to be exposed to Lovelace/browser JavaScript.
- Home Assistant becomes the authenticated boundary.
- The card communicates using Home Assistant's existing authenticated WebSocket connection.
- Todoist API behavior can change without requiring UI code to own the integration logic.
- Multiple dashboard clients can use the same backend.
- It avoids CORS/authentication hacks in a kiosk browser.

---

## 3. Existing Code to Reuse

The existing custom card is:

```text
https://github.com/Madsebase/todoist-task-flow
```

The user originally referenced:

```text
https://github.com/Zensqrl/todoist-task-flow
```

At the time this specification was prepared, the active repository is under `Madsebase/todoist-task-flow`.

### Important existing behavior

The card already follows a useful Home Assistant-native pattern.

It currently retrieves tasks approximately like:

```javascript
const response = await this._hass.callWS({
  type: "todo/item/list",
  entity_id: this.currentEntity
});
```

It currently completes tasks using Home Assistant's `todo.update_item` service and adds tasks using `todo.add_item`.

The card already includes useful UI code for:

- task list rendering
- date formatting
- filtering
- refresh behavior
- task completion interaction
- add-task input
- visual editor/configuration
- themes
- compact/mobile layouts
- scroll-position preservation
- loading states

### Direction

**Fork/extend this card rather than rebuilding the entire frontend from scratch.**

The frontend should gradually stop depending on the generic Home Assistant `todo/item/list` data model for Todoist Enhanced mode and instead call WebSocket commands exposed by the new `todoist_enhanced` integration.

Do not remove generic behavior unnecessarily if it can coexist cleanly. However, prioritize a simple working Todoist Enhanced mode over maintaining every legacy option in the first implementation.

---

## 4. Why the Standard Home Assistant Todoist Path Is Insufficient

Home Assistant's generic to-do item representation includes only a limited set of task fields for this use case, such as:

- summary
- uid
- status
- due
- description
- priority

The required dashboard needs Todoist-specific information and behavior, especially:

- native Todoist filter queries
- project identity/name
- section identity/name
- labels
- deadline
- recurring status
- richer Todoist task IDs/metadata
- future extensibility for task-specific Todoist operations

Do not try to force all of this into Home Assistant entity state attributes or create a sensor containing a giant task array.

The richer task collection should be requested on demand through custom Home Assistant WebSocket commands.

---

## 5. Todoist API Capabilities to Use

Use the current Todoist API v1.

Base URL:

```text
https://api.todoist.com/api/v1
```

Authorization:

```http
Authorization: Bearer <TOKEN>
```

### 5.1 Execute a Todoist filter

Primary endpoint:

```http
GET /api/v1/tasks/filter
```

Query parameter:

```text
query=<Todoist filter expression>
```

Example conceptually:

```http
GET /api/v1/tasks/filter?query=(due before: first day | deadline before: first day) & (!#Daily Checklist | today)
```

The endpoint is cursor-paginated.

A response has the form:

```json
{
  "results": [],
  "next_cursor": "..."
}
```

Implement pagination until `next_cursor` is null/absent.

Use `limit=200` unless there is a reason not to.

Do not use Todoist's comma operator to combine multiple filters through this endpoint; the API documentation states that multiple filters using the comma operator are not supported here.

### 5.2 Complete a task

Use:

```http
POST /api/v1/tasks/{task_id}/close
```

This is important for recurring tasks: Todoist documents this operation as behaving like its official clients. Regular tasks are completed; recurring tasks advance to their next occurrence.

Do **not** implement recurring-task completion by deleting the task.

### 5.3 Add a task

For MVP, prefer Todoist Quick Add:

```http
POST /api/v1/tasks/quick
```

Example request:

```json
{
  "text": "Buy furnace filter tomorrow #Home @errands p2",
  "meta": true
}
```

Quick Add uses Todoist's own natural-language parser and supports, among other things:

- dates/times
- `#Project`
- `/Section`
- `@label`
- priorities
- assignees
- deadlines
- reminders
- description syntax

This avoids creating a large structured task editor in the kiosk.

The frontend can begin with one text input:

```text
Add a task...
```

and send the complete string to the backend.

### 5.4 Projects

Use:

```http
GET /api/v1/projects
```

This is cursor-paginated.

Cache an ID-to-project-name mapping:

```python
projects_by_id = {
    "abc123": "Home",
    "def456": "Daily Checklist",
}
```

### 5.5 Sections

Use:

```http
GET /api/v1/sections
```

This is cursor-paginated.

Cache an ID-to-section-name mapping.

### 5.6 Saved Todoist filters

Todoist saved filters are available from the Sync API as the `filters` resource type.

Use:

```http
POST /api/v1/sync
```

with:

```text
sync_token=*
resource_types=["filters"]
```

A filter object includes at least:

```json
{
  "id": "4638878",
  "name": "Important",
  "query": "priority 1",
  "is_deleted": false
}
```

The integration should eventually support selecting a **saved Todoist filter by name or ID** and then executing the saved filter's `query` through `/tasks/filter`.

For the first vertical slice, it is acceptable to configure the raw filter expression directly if that gets a functioning end-to-end result sooner. Saved-filter resolution should then be added immediately after the basic query path works.

---

## 6. Home Assistant Custom Integration

Suggested domain:

```text
todoist_enhanced
```

Suggested directory:

```text
custom_components/todoist_enhanced/
```

Suggested initial structure:

```text
custom_components/todoist_enhanced/
├── __init__.py
├── manifest.json
├── const.py
├── config_flow.py
├── api.py
├── models.py
├── websocket.py
├── coordinator.py
├── diagnostics.py          # optional after MVP
├── strings.json
└── translations/
    └── en.json
```

This exact structure can be adjusted to match current Home Assistant development conventions.

### 6.1 Authentication/configuration

For MVP, implement a Home Assistant Config Flow that asks for the user's Todoist API token.

Requirements:

- Validate the token by making a small Todoist API request.
- Store the token in the Home Assistant config entry.
- Never send the token to the frontend.
- Never log the token.
- Redact the token from diagnostics.
- Use Home Assistant's shared async HTTP client/session where appropriate.
- Set sensible request timeouts.

Do **not** depend on private/internal objects from Home Assistant's official Todoist integration to steal/reuse its token. That would create an unstable dependency.

OAuth can be considered later; it is not required for the initial personal installation.

### 6.2 API client

Create a small typed async Todoist API client.

Conceptual interface:

```python
class TodoistEnhancedApi:
    async def get_tasks_by_filter(self, query: str) -> list[TodoistTask]: ...

    async def get_projects(self) -> list[TodoistProject]: ...

    async def get_sections(self) -> list[TodoistSection]: ...

    async def get_saved_filters(self) -> list[TodoistFilter]: ...

    async def close_task(self, task_id: str) -> None: ...

    async def quick_add_task(self, text: str) -> TodoistTask | dict: ...
```

Requirements:

- Centralize HTTP code.
- Centralize authorization headers.
- Handle cursor pagination generically.
- Raise clear integration-specific exceptions.
- Handle 401/403 separately from transient failures.
- Handle Todoist 400 responses as user/query errors where appropriate.
- Do not leak raw token-containing request information into logs.

### 6.3 Metadata cache/coordinator

Project and section lists change much less frequently than the filtered task list.

Maintain mappings such as:

```python
project_name_by_id: dict[str, str]
section_name_by_id: dict[str, str]
```

Saved filters may also be cached.

A reasonable initial strategy:

- Load project/section/filter metadata on integration startup.
- Refresh metadata periodically (for example every 15–60 minutes).
- Allow an explicit refresh command.
- Fetch task-query results on demand.
- Do not poll Todoist every few seconds.

Avoid premature complexity. A standard Home Assistant `DataUpdateCoordinator` may be useful for metadata, but task filter requests do not have to be modeled as entities.

---

## 7. Backend Data Model Returned to the Card

Do not send the raw Todoist response directly to the card forever.

Normalize it into a stable internal/frontend contract.

Suggested task object:

```json
{
  "id": "6XGgmFVcrG5RRjVr",
  "content": "Change furnace filter",
  "description": "Use MERV 11 filter",
  "project_id": "6XGgm6PHrGgMpCFX",
  "project_name": "Home",
  "section_id": "6fFPHV272WWh3gpW",
  "section_name": "Maintenance",
  "parent_id": null,
  "labels": ["house"],
  "priority": 2,
  "due": {
    "date": "2026-08-20",
    "datetime": null,
    "string": "Thursday",
    "is_recurring": false
  },
  "deadline": {
    "date": "2026-08-31"
  },
  "duration": null,
  "is_completed": false,
  "url": null
}
```

Notes:

- Preserve Todoist's real task ID.
- Do not use task title/content as the mutation key.
- Fields may be `null`.
- Normalize date-only vs datetime values carefully.
- Preserve both the useful parsed date and Todoist's human expression when available.
- It is fine to add fields later without breaking the MVP.

### Priority

Verify Todoist's current API priority semantics before creating UI labels/colors. Do not assume Home Assistant's generic priority representation matches Todoist's API representation.

---

## 8. Home Assistant WebSocket Interface

Home Assistant officially supports extending its frontend WebSocket API from an integration.

Register custom commands during integration setup.

Suggested commands:

### 8.1 Get tasks

Request:

```json
{
  "type": "todoist_enhanced/tasks",
  "filter": "(due before: first day | deadline before: first day) & (!#Daily Checklist | today)"
}
```

Response:

```json
{
  "tasks": [
    {
      "id": "...",
      "content": "...",
      "project_name": "Home",
      "due": {},
      "deadline": {},
      "priority": 2,
      "labels": []
    }
  ]
}
```

Alternative after saved-filter support:

```json
{
  "type": "todoist_enhanced/tasks",
  "filter_id": "4638878"
}
```

or:

```json
{
  "type": "todoist_enhanced/tasks",
  "filter_name": "Enhanced Upcoming"
}
```

The backend should resolve the saved filter and execute its query.

### 8.2 Get saved filters

Request:

```json
{
  "type": "todoist_enhanced/filters"
}
```

Response:

```json
{
  "filters": [
    {
      "id": "4638878",
      "name": "Enhanced Upcoming",
      "query": "..."
    }
  ]
}
```

### 8.3 Complete task

Request:

```json
{
  "type": "todoist_enhanced/complete_task",
  "task_id": "6XGgmFVcrG5RRjVr"
}
```

Expected behavior:

1. Validate `task_id`.
2. Call Todoist `POST /tasks/{id}/close`.
3. Return success.
4. Frontend refreshes current filter.

### 8.4 Quick add

Request:

```json
{
  "type": "todoist_enhanced/quick_add",
  "text": "Buy furnace filter tomorrow #Home"
}
```

Response should include enough information to indicate success and, if Todoist returns useful parsed metadata, optionally return it.

### 8.5 Refresh metadata

Optional:

```json
{
  "type": "todoist_enhanced/refresh_metadata"
}
```

This is not essential to the first vertical slice.

---

## 9. WebSocket Security

WebSocket commands must require an authenticated Home Assistant connection.

Do not accept Todoist tokens in WebSocket messages.

For this personal kiosk use case, normal authenticated HA users may initially be allowed to use the commands.

Keep the command schemas strict:

- required command `type`
- string length validation
- non-empty task IDs
- filter-query maximum aligned with Todoist's API where practical
- reject unsupported input instead of silently guessing

Network I/O handlers must use Home Assistant's async WebSocket response pattern.

---

## 10. Lovelace Card

Suggested eventual card type:

```yaml
type: custom:todoist-enhanced-card
```

It may begin as a fork/mode of `todoist-task-flow`.

### 10.1 MVP display fields

Each task row should prioritize:

1. completion checkbox
2. task content/title
3. due date/time
4. project name
5. priority
6. deadline, when present
7. labels, when useful

Description can be hidden by default and shown in an expandable detail area.

### 10.2 Kiosk UX principles

This is designed for a touch kiosk, not a desktop Todoist replacement.

Optimize for:

- large touch targets
- readable task rows
- very few modal dialogs
- immediate visual feedback
- no horizontal scrolling
- good behavior on tablet-sized screens
- graceful loading/error states
- preserving scroll position when possible
- minimal typing for common actions

### 10.3 Completion behavior

On checkbox/tap:

1. Optimistically disable the row or show a loading state.
2. Call:

```javascript
hass.callWS({
  type: "todoist_enhanced/complete_task",
  task_id: task.id
});
```

3. On success:
   - remove the completed task immediately from the displayed list, or
   - refresh the active Todoist filter.
4. On failure:
   - restore the row.
   - show a concise error.

Do not identify tasks by their title.

### 10.4 Task retrieval

Replace the current generic path:

```javascript
hass.callWS({
  type: "todo/item/list",
  entity_id: ...
});
```

with the new integration's command when the card is in Todoist Enhanced mode:

```javascript
hass.callWS({
  type: "todoist_enhanced/tasks",
  filter_name: this.config.filter_name
});
```

or raw-query mode:

```javascript
hass.callWS({
  type: "todoist_enhanced/tasks",
  filter: this.config.filter
});
```

### 10.5 Add task

For MVP:

```text
[ Add a task...                               ] [+]
```

Send the full input to `todoist_enhanced/quick_add`.

Example user entry:

```text
Replace HVAC filter Saturday #Home @maintenance p2
```

After success:

- clear input
- refresh current filtered task list
- show a subtle success state if useful

### 10.6 Refresh

Support:

- manual refresh button
- refresh after add/complete
- modest background refresh

The existing card currently uses a long periodic refresh interval. Keep background network usage conservative.

A 5–10 minute automatic refresh is reasonable for the first implementation, with explicit refresh after mutations.

---

## 11. Suggested Card Configuration

Initial raw-query configuration could look like:

```yaml
type: custom:todoist-enhanced-card
title: Tasks
filter: >-
  (due before: first day | deadline before: first day) &
  (!#Daily Checklist | today)
show_project: true
show_due: true
show_deadline: true
show_priority: true
show_labels: false
show_description: expandable
allow_complete: true
allow_quick_add: true
```

Once saved filters are implemented, prefer:

```yaml
type: custom:todoist-enhanced-card
title: Tasks
filter_name: Enhanced Upcoming
allow_complete: true
allow_quick_add: true
```

The saved Todoist filter should then become the source of truth for filtering logic.

If the Todoist filter changes in Todoist, the Home Assistant card should use the new query without requiring the Lovelace YAML to be edited.

---

## 12. Saved Filter Resolution

Implement saved filters in two phases.

### Phase A — raw query

Prove that:

```text
HA Card -> custom WS -> Todoist /tasks/filter -> normalized results -> card
```

works.

### Phase B — saved filter

On backend metadata refresh:

1. Request Sync API resource `filters`.
2. Ignore deleted filters.
3. Store them by both ID and name.
4. When frontend supplies `filter_name`, resolve it.
5. Execute the filter object's `query` through `/tasks/filter`.

If multiple filters somehow have the same name, prefer requiring/configuring the stable filter ID rather than guessing.

Expose filter IDs in the visual card editor if practical.

---

## 13. Error Handling

Define useful frontend-facing error codes.

Examples:

```text
auth_failed
filter_not_found
invalid_filter
todoist_unavailable
task_not_found
quick_add_failed
rate_limited
unknown_error
```

The backend should translate Todoist/HTTP failures into stable error responses instead of sending arbitrary exceptions to the frontend.

Suggested behavior:

### 401 / 403

- mark integration authentication problem
- return `auth_failed`
- surface a repair/re-auth path in Home Assistant if practical

### 400 from `/tasks/filter`

- return `invalid_filter`
- include a short safe message
- never crash the card

### 429

- return `rate_limited`
- respect `Retry-After` if provided
- do not hammer the API with retries

### Network/5xx

- return `todoist_unavailable`
- preserve the previously rendered list if possible

---

## 14. Testing Requirements

### 14.1 Backend unit tests

Mock Todoist HTTP calls.

Cover:

- successful filtered task query
- filter pagination
- project pagination
- section pagination
- saved filter retrieval
- saved filter resolution by ID
- saved filter resolution by name
- missing saved filter
- malformed filter
- 401
- 403
- 429
- Todoist 5xx
- close normal task
- close recurring task request path
- Quick Add
- null/missing due date
- deadline without due date
- section/project IDs missing from metadata cache

### 14.2 WebSocket tests

Cover:

- authenticated request succeeds
- bad schema rejected
- task list serialized correctly
- completion calls correct task ID
- raw filter accepted
- configured/saved filter accepted
- API errors translated correctly

### 14.3 Frontend tests/manual checks

At minimum manually verify:

- initial load
- empty filter result
- long task names
- descriptions
- due date only
- due datetime
- overdue
- deadline
- priority
- labels
- completion
- recurring-task completion
- Quick Add
- API failure
- Home Assistant reconnect
- tablet/kiosk layout
- scroll behavior after refresh

---

## 15. MVP Acceptance Criteria

The MVP is complete when all of the following are true:

### Setup

- The `todoist_enhanced` integration can be installed in Home Assistant.
- A user can configure it with a Todoist API token.
- Invalid tokens fail configuration cleanly.

### Filtering

- The card can request this exact filter:

```text
(due before: first day | deadline before: first day) & (!#Daily Checklist | today)
```

- Todoist, not Home Assistant, evaluates the filter.
- All cursor pages are retrieved.
- Results displayed in Home Assistant match the corresponding Todoist filter closely enough to validate the architecture.

### Display

Each task can show:

- content
- project name
- due date/time
- priority
- deadline when present

Labels/description should be supported in the data model even if not prominent in the first UI.

### Complete

- Tapping a task's checkbox calls Todoist using the Todoist task ID.
- A normal task becomes completed.
- A recurring task advances correctly rather than being permanently deleted.
- The card updates after completion.

### Add

- The kiosk has an add-task field.
- Entering Quick Add text creates the correct Todoist task.
- The card refreshes after creation.

### Security

- No Todoist token appears in frontend source/config/network messages.
- The browser communicates only with Home Assistant.
- Sensitive data is not logged.

---

## 16. Out of Scope for MVP

Do **not** spend initial implementation time recreating full Todoist functionality.

Explicitly out of scope unless required to make the architecture work:

- full task-edit dialog
- comments
- attachments
- activity history
- completed-task history
- drag/drop ordering
- project administration
- section administration
- label administration
- filter creation/editing
- collaboration
- assignee management UI
- reminders UI
- location reminders
- boards
- productivity/Karma
- offline mutation queue
- Todoist-style search UI
- full OAuth distribution flow

Keep the project narrow.

---

## 17. Future Enhancements

After MVP, likely useful enhancements are:

1. **Saved-filter picker**
   - visual card editor lists filters from Todoist.

2. **Multiple filter tabs**
   - e.g. `Today`, `Upcoming`, `Errands`, `House`.

3. **Task detail expansion**
   - description, labels, section, deadline.

4. **Structured add dialog**
   - optional project/due/priority controls in addition to Quick Add.

5. **Edit due date**
   - simple "Today / Tomorrow / Next week / Pick date" actions.

6. **Open in Todoist**
   - optional deep-link for rare advanced editing.

7. **Push-style refresh**
   - explore Todoist sync/webhook options only if polling becomes a real problem.

Do not implement these before the core vertical slice is stable.

---

## 18. Suggested Development Sequence for Codex

### Step 1 — Inspect environment and source

Before editing:

- locate the current Home Assistant configuration directory
- locate the installed `todoist-task-flow` card
- inspect its source
- identify the Home Assistant version
- inspect current custom integration patterns already present in the user's instance

Do not modify unrelated Home Assistant configuration.

### Step 2 — Scaffold `todoist_enhanced`

Create the custom integration skeleton:

```text
custom_components/todoist_enhanced/
```

Implement:

- manifest
- constants
- config flow
- API-token validation
- Todoist async API client

Restart/reload and confirm the integration loads without errors.

### Step 3 — Prove filter retrieval

Hard-code or temporarily expose a backend test path for:

```text
(due before: first day | deadline before: first day) & (!#Daily Checklist | today)
```

Confirm Todoist returns the expected tasks.

Implement pagination.

Do not work on visual polish until this succeeds.

### Step 4 — Add project/section metadata

Fetch projects and sections.

Normalize task results into the frontend data contract.

Verify project names appear correctly.

### Step 5 — Add custom WebSocket command

Implement:

```text
todoist_enhanced/tasks
```

Call it from browser developer tools or a minimal test card and verify the result.

### Step 6 — Adapt the existing card

Fork/refactor `todoist-task-flow`.

Change only the task data source first.

Retain useful rendering/layout code.

Display:

- title
- project
- due
- deadline
- priority

### Step 7 — Complete task

Implement backend:

```text
todoist_enhanced/complete_task
```

Use:

```text
POST /api/v1/tasks/{task_id}/close
```

Update card action to use task ID.

Test both one-time and recurring tasks.

### Step 8 — Quick Add

Implement:

```text
todoist_enhanced/quick_add
```

Connect the existing add-task input to it.

Verify syntax such as:

```text
Buy furnace filter tomorrow #Home @errands p2
```

### Step 9 — Saved filters

Fetch `filters` via Sync API.

Support `filter_name` and preferably `filter_id`.

Change the kiosk configuration from a hard-coded expression to the user's saved Todoist filter.

### Step 10 — Harden and test

Add:

- error mapping
- loading states
- auth failure handling
- API timeouts
- rate-limit behavior
- backend tests
- frontend validation
- documentation

Only after this should broader UI customization be considered.

---

## 19. Implementation Preferences

Use these engineering preferences unless the local Home Assistant version or current official guidance strongly indicates otherwise:

### Python

- async/await throughout network paths
- Home Assistant's shared async HTTP session
- type annotations
- dataclasses or lightweight typed models where useful
- small methods
- explicit error classes
- no blocking requests library
- no token logging

### JavaScript/TypeScript

The existing card is plain JavaScript. For the first fork, staying close to its current implementation is acceptable and likely faster.

Do not introduce a large frontend framework solely for this project.

If restructuring substantially, Lit is reasonable because it aligns well with Home Assistant custom-card development, but migration to Lit is **not an MVP requirement**.

### State

- backend owns Todoist integration state/credentials
- frontend owns transient presentation state
- Todoist remains source of truth for tasks and saved filters
- do not duplicate task state into HA sensors unless a future automation use case requires it

---

## 20. Things Codex Should Verify Rather Than Assume

Before implementation, verify against current official documentation/source:

1. Current Todoist API v1 request/response schemas.
2. Current Home Assistant custom integration WebSocket registration API.
3. Current Home Assistant config-flow conventions.
4. Current recommended HTTP session helper.
5. Current custom-card APIs.
6. Todoist priority value semantics.
7. Todoist Quick Add response shape.
8. Whether any relevant Todoist API endpoint behavior changed after this document was prepared.
9. Whether the existing `todoist-task-flow` repository has moved or materially changed.

When official docs disagree with this specification on low-level mechanics, follow current official docs while preserving the architecture and product requirements described here.

---

## 21. Do Not Take These Shortcuts

Avoid the following:

### Do not embed Todoist in an iframe

The goal is a native kiosk surface with a few selected capabilities, not a Todoist webpage inside HA.

### Do not call Todoist directly from the card

No API token in JavaScript/Lovelace.

### Do not recreate Todoist filter semantics

Send the native filter expression to Todoist.

### Do not create a huge sensor attribute containing tasks

Use the WebSocket API for on-demand structured data.

### Do not couple to Home Assistant's official Todoist integration internals

It is fine for both integrations to coexist, but this component should own its own supported Todoist API client.

### Do not identify tasks by title

Use Todoist task IDs for mutations.

### Do not delete recurring tasks to simulate completion

Use Todoist's close-task operation.

### Do not expand scope into a Todoist clone

Optimize for kiosk usefulness.

---

## 22. Primary User Story

> As a person standing at a Home Assistant household kiosk, I want to see the Todoist tasks that currently matter according to my existing Todoist filter, check tasks off, and quickly add a new task, without opening the Todoist application.

Everything in the MVP should support this story.

---

## 23. Concrete First Target

For the first working demo, configure a single dashboard card with the filter:

```text
(due before: first day | deadline before: first day) & (!#Daily Checklist | today)
```

The demo must:

1. Display the tasks Todoist returns.
2. Show project name.
3. Show due date/time.
4. Show deadline where applicable.
5. Show priority.
6. Allow a task to be completed.
7. Allow a task to be added using Quick Add.
8. Refresh correctly after either action.

Do this before building configuration editors, multiple filters, additional actions, or elaborate visual customization.

---

## 24. Reference URLs

These references were checked when this document was prepared.

### Todoist

Todoist API v1:

```text
https://developer.todoist.com/api/v1/
```

Relevant API areas:

```text
GET  https://api.todoist.com/api/v1/tasks/filter
POST https://api.todoist.com/api/v1/tasks/quick
POST https://api.todoist.com/api/v1/tasks/{task_id}/close
GET  https://api.todoist.com/api/v1/projects
GET  https://api.todoist.com/api/v1/sections
POST https://api.todoist.com/api/v1/sync
```

### Home Assistant

Official Todoist integration:

```text
https://www.home-assistant.io/integrations/todoist/
```

Extending Home Assistant WebSocket API:

```text
https://developers.home-assistant.io/docs/frontend/extending/websocket-api/
```

Custom card development:

```text
https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/
```

### Existing projects to inspect

Todoist Task Flow:

```text
https://github.com/Madsebase/todoist-task-flow
```

Home Tasks, useful as an architectural/reference implementation for richer task handling:

```text
https://github.com/L3t4l3s/home-tasks
```

---

# Initial Codex Instruction

Begin by inspecting the current Home Assistant environment and the existing `todoist-task-flow` card. Then implement the smallest end-to-end vertical slice:

```text
Todoist filter
    ↓
todoist_enhanced backend
    ↓
Home Assistant WebSocket
    ↓
forked task-flow card
    ↓
render matching tasks
```

Do not begin with visual redesign.

Once filtered task retrieval is functioning, add project-name enrichment, then task completion, then Quick Add, then saved-filter resolution.

Keep all Todoist API access in the backend, use Todoist task IDs for mutations, and treat Todoist's native filter engine as the source of truth for filter semantics.
