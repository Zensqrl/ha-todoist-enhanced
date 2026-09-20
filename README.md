# Todoist Enhanced for Home Assistant

Reliable Todoist facts for a Daily Decision Dashboard: all active tasks, native
filters, rich metadata, labels/catalogs, and explicit freshness/completeness.
Credentials and Todoist API traffic remain on the Home Assistant backend.

This is a **helper integration**, not a replacement for native Todoist. It does not
create or modify native `todo` or calendar entities. Ranking policy, scheduling and
the future Bubble-style dashboard card are separate work.

## Install

Requires Home Assistant 2026.9 or newer. Add `Zensqrl/ha-todoist-enhanced` to HACS as
an Integration repository, download, restart HA, then add **Todoist Enhanced** in
Settings → Devices & services. Enter your Todoist personal API token in that form;
do not put it in dashboard YAML or send it to a chat.

Manual installation: copy `custom_components/todoist_enhanced` into HA's
`custom_components` directory and restart. One account is supported.

Build a clean manual-install ZIP with `python scripts/build_release.py`. Extract
its `custom_components` folder into the HA configuration directory, then restart
and add the integration through Settings. Generated ZIPs are excluded from Git.

The new domain is `todoist_enhanced`. For a previous experimental installation with
a differently named domain, remove only that experimental config entry through HA,
install this version, and configure it again. Do not edit `.storage` or remove the
native Todoist entry. No automatic cross-domain migration is provided. Update custom
API consumers to the documented v1 envelope; the earlier companion card is not a
supported frontend for this release.

## Read dashboard data

WebSocket, using the already-authenticated Home Assistant connection:

```json
{"id":1,"type":"todoist_enhanced/tasks","force_refresh":true}
```

No selector means all active tasks, including undated and future tasks.

```json
{"id":2,"type":"todoist_enhanced/catalogs"}
```

HA actions `todoist_enhanced.get_tasks` and `todoist_enhanced.get_catalogs` provide
the same structured responses to scripts and automations. Completion and Quick Add
are separate write operations. See [the complete contract](docs/data-contract.md)
for selectors, permissions, freshness, errors, field semantics and examples.

The original upcoming view remains supported as a filter:

```text
(due before: first day | deadline before: first day) & (!#Daily Checklist | today)
```

Do not use that filtered view as the only source for task suitability decisions.
It can omit actionable undated tasks.

## Single-package frontend architecture

This repository owns the integration and its future bundled card. No separate card
installation is required to use the data API. The Bubble-style card is not implemented
yet. Its eventual compiled asset belongs under
`custom_components/todoist_enhanced/frontend/`; source/build files can live at the
repository root. See [frontend packaging](docs/frontend-packaging.md).

## Development

Use Linux and Python 3.14 with the pinned Home Assistant test environment:

```sh
pip install -r requirements-test.txt
pytest -q
```

Tests include API fixtures, cursor failures/deduplication, raw metadata semantics,
cache recovery and concurrency, and actual HA service/WebSocket/config-entry tests.
They do not replace live account validation. No tests intentionally create real
Todoist tasks or labels.

Current implementation keeps a small isolated async HTTP adapter. The official
Todoist SDK provides many operations, but adding it now would introduce version
coupling while still requiring saved-filter/catalog coverage and raw-field handling.
The adapter can be replaced behind the shared backend without changing dashboard
consumers. No separate Python package is necessary for this custom helper release.
