# Repository Instructions

`mythosaur-workspace` is the standalone MCP service and plugin repository for
Google Workspace and NotebookLM.

## Current boundary

- This repository owns the Google Workspace and NotebookLM MCP handlers,
  authentication configuration, container, Codex plugin, focused skills,
  marketplace metadata, release artifact, and tests.
- Tool names and result envelopes stay compatible with the former
  `mythosaur-tools` implementation during migration.
- `mythosaur.memory`, homelab, search, outdoor, travel, and finance capabilities
  are outside this repository.
- The plugin exposes only this service's tool catalog. The MCP server remains
  responsible for authentication and read/write policy.

## Working rules

- Keep the plugin focused on Calendar, Gmail, Drive, Docs, Sheets, Photos,
  Maps, and NotebookLM user workflows.
- Author shared skills once under `skills/shared/`; plugin skill entries are
  development symlinks and packaged releases contain real files.
- Keep secrets, tokens, Google credential files, API keys, and NotebookLM
  profiles out of the repository and release artifacts.
- Keep the runtime independently startable and testable without a
  `mythosaur-tools` checkout.
- Preserve compatibility tests until the upstream handlers are retired.
- Run `make check` after changes and `make package` before a release handoff.
- Do not commit or push unless the user asks.
