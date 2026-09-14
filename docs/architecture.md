# Architecture

## Runtime boundary

`mythosaur-workspace` is an independently deployable MCP service and plugin.

```text
Codex
  -> mythosaur-workspace plugin
     -> focused skills
     -> mythosaur-workspace MCP server
        -> mythosaur.google_workspace
           -> Google APIs
           -> NotebookLM CLI
```

This repository owns all 34 Google Workspace and NotebookLM tool handlers,
their schemas and result envelopes, MCP OAuth authentication, read/write
profile, container, plugin discovery, skill routing, package construction, and
release validation. It runs without a `mythosaur-tools` checkout.

## Trust boundary

The plugin points to the loopback-only service and asks Codex to use OAuth. The
MCP SDK owns discovery, Dynamic Client Registration, PKCE verification, token
exchange, and revocation. A thin in-process adapter redirects Google Workspace
consent through the same service and issues short-lived, resource-bound MCP
tokens. The plugin contains no credential value.

The server validates every MCP request and defaults to
`MW_PROFILE=readonly`; write tools return a `readonly` error before reaching
Google or NotebookLM unless the operator explicitly uses the power profile.

Google OAuth credentials, refreshed tokens, and hashed MCP token records live
under `secrets/`; DCR client metadata is stored there, including a client
secret only when the client uses confidential authentication. Files are
atomically written with user-only permissions. NotebookLM profile state lives under `secrets/notebooklm/`.
Those paths are mounted at runtime and excluded from Git and plugin packages.
File uploads are limited to the mounted `shared/` directory.

Google OAuth remains one local-user credential rather than a multi-user store.
Maps API-key authentication and NotebookLM browser-profile authentication are
separate trust boundaries.

`mythosaur.memory` remains in `mythosaur-tools` because it writes
repository-owned memory files and depends on Mythosaur mutation receipts and
lifecycle policy. It is not part of the Google Workspace product boundary.

## Compatibility and cutover

The initial extraction preserves the existing tool names, input schemas,
`mythosaur.google_workspace` plugin ID, and `{status, tool, data, error, meta}`
result envelope. Existing handlers remain in `mythosaur-tools` temporarily as
a rollback path.

Remove the upstream handlers only after:

1. the standalone server reports exactly 34 tools;
2. copied handler tests and MCP transport smoke tests pass;
3. the Codex plugin connects to the standalone endpoint and completes real
   Calendar, Gmail, Drive or Docs, Sheets, and NotebookLM read checks;
4. write behavior is verified deliberately under the power profile;
5. the upstream full plugin no longer advertises Workspace tools.

Until those checks are complete, this repository is implemented locally but
not claimed as deployed or cut over.

The transition release retains `MW_MCP_AUTH_MODE=api_key` only as rollback.
After a packaged OAuth install passes live reads, restart/refresh,
reauthentication, deliberate power-mode writes, and rollback verification, the
following release removes API-key ingress and its tests and documentation.
