# Todoist Kiosk for Home Assistant

Todoist Kiosk is a custom Home Assistant integration that keeps Todoist credentials and API traffic on the Home Assistant backend. Its companion Lovelace card can run native Todoist filters, display richer task metadata, complete tasks safely (including recurring tasks), and create tasks with Todoist Quick Add.

## Architecture

```text
Todoist API v1 <-- bearer token -- Home Assistant todoist_kiosk integration
                                      ^
                                      | authenticated HA WebSocket
                                      v
                               Todoist Kiosk card
```

The browser never receives the Todoist API token and never calls `api.todoist.com`.

## Installation

### Integration

With HACS, add this repository as a custom **Integration** repository and install **Todoist Kiosk**. For a manual installation, copy `custom_components/todoist_kiosk` into the Home Assistant configuration directory under `custom_components/`, then restart Home Assistant.

In Home Assistant:

1. Open **Settings → Devices & services → Add integration**.
2. Search for **Todoist Kiosk**.
3. Enter the personal API token from Todoist **Settings → Integrations → Developer**.

The setup flow validates the token before storing the config entry. One Todoist account is supported in the initial version.

### Card

Install the companion [`todoist-task-flow`](https://github.com/Zensqrl/todoist-task-flow) repository through HACS Frontend, or copy its `todoist-task-flow.js` file to `/config/www/` and register `/local/todoist-task-flow.js` as a JavaScript module dashboard resource.

## Card configuration

The first target filter from the implementation brief can be configured directly:

```yaml
type: custom:todoist-kiosk-card
title: Tasks
filter: >-
  (due before: first day | deadline before: first day) &
  (!#Daily Checklist | today)
show_project: true
show_due: true
show_deadline: true
show_priority: true
show_labels: false
allow_complete: true
allow_quick_add: true
```

Todoist evaluates the filter expression. The integration does not implement or approximate Todoist's filter grammar.

To keep the filter source of truth in Todoist, use a saved filter:

```yaml
type: custom:todoist-kiosk-card
title: Tasks
filter_name: Kiosk Upcoming
```

You can use `filter_id` instead of `filter_name`. IDs are required if saved filters have duplicate names. Configure only one selector; if more than one is present the card uses `filter_id`, then `filter_name`, then `filter`.

## WebSocket API

All commands use Home Assistant's authenticated WebSocket connection:

| Command | Purpose |
| --- | --- |
| `todoist_kiosk/tasks` | Execute a raw or saved Todoist filter and return normalized tasks |
| `todoist_kiosk/filters` | List active saved filters |
| `todoist_kiosk/complete_task` | Close a task by Todoist ID |
| `todoist_kiosk/quick_add` | Create a task using Todoist natural-language parsing |
| `todoist_kiosk/refresh_metadata` | Refresh projects, sections, and saved filters |

Project, section, and saved-filter metadata refresh every 30 minutes. Task results are fetched on demand by the card, every 10 minutes in the background, and immediately after mutations.

## Development and validation

The dependency-free backend unit suite covers pagination, saved filters, normalization, error mapping, close/Quick Add paths, and WebSocket command behavior:

```bash
python3 -m unittest discover -v
```

The card repository includes a Node smoke test:

```bash
node tests/card.test.js
```

Live validation still requires a Home Assistant instance and a Todoist account. In particular, manually compare the card results with the same filter in Todoist and verify both normal and recurring task completion.

## Security and diagnostics

- The API token is stored in the Home Assistant config entry only.
- WebSocket messages never accept or return a Todoist token.
- HTTP errors are translated to stable frontend-safe codes.
- Diagnostics redact the token and report metadata counts only.
- Task mutations use Todoist task IDs, never task titles.
