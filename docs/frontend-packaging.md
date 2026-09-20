# Future frontend delivery

The helper release intentionally has no visual card. Build the Bubble-style card
against `docs/data-contract.md` after running-instance acceptance.

- Ship the compiled module inside `custom_components/todoist_enhanced/frontend/`.
- Register `custom:todoist-enhanced-card`, not the generic predecessor's element.
- Use one integration version/release for backend and frontend.
- Serve only the compiled public frontend directory through HA's
  `async_register_static_paths` / `StaticPathConfig`. Never serve config or Python directories.
- Register a versioned module URL once in storage-mode Lovelace; update only the
  integration-owned entry. Support YAML-managed resources through documented manual
  configuration. Do not write `.storage` files directly.
- Remove only integration-owned resources when the last config entry is removed.
- Test setup/reload/unload, browser cache refresh, protocol-version mismatch,
  reconnect, and resource duplication before shipping a card.
- Subscribe to `todoist_enhanced_updated` and coalesce reads; keep old task contents
  with a visible stale/error state rather than rendering failures as empty success.
- Authentication is HA's existing connection. All Todoist traffic stays server-side.

These are packaging requirements for the next phase, not claims of an installed
frontend or implemented resource lifecycle in the helper release.
