<div align="center">

<img src="plugins/mythosaur-workspace/assets/logo.svg" width="96" alt="Mythosaur Workspace logo">

# Mythosaur Workspace

**Use Google Workspace and NotebookLM from Codex through a focused local MCP service.**

[Start here](#start-here) · [Commands](#commands) · [Read the guides](#guides)

</div>

Mythosaur Workspace gives Codex focused access to Google Calendar, Gmail,
Drive, Docs, Sheets, Photos, Maps, and NotebookLM. The repository contains the
standalone service, Codex plugin, authentication setup, and release package.

The path from a Codex task to an authenticated Workspace action is:

**Codex → plugin → local MCP service → Google APIs or NotebookLM**

The service exposes 34 tools. It defaults to read-only access. Write access
requires an explicit power-profile change and a second consent flow.

## What it includes

- Google Calendar and Gmail
- Google Drive, Docs, and Sheets
- Google Photos and Maps
- NotebookLM notebooks, sources, queries, and generated artifacts
- Focused Workspace and NotebookLM routing

The plugin deliberately excludes Mythosaur memory, homelab, generic web
research, outdoor, travel, and finance tools. Generic `action-triage` and
`evidence-briefing` skills remain in the `mythosaur-tools` plugin so installing
both plugins does not register duplicate skill names.

## Start here

You need Docker, `uv`, the Codex CLI, and a Google Cloud Desktop OAuth client.
Follow the [Google OAuth credential setup guide](docs/setup.md#2-prepare-google-access),
then save the downloaded JSON file as `secrets/google-credentials.json` before
running `make install`; the command stops if this file is missing.

```bash
cp .env.example .env
mkdir -p secrets
cp /path/to/downloaded-client.json secrets/google-credentials.json
```

Then install the local plugin and sign in to both Google Workspace and
NotebookLM:

```bash
make install
make notebooklm-login
```

`make install` starts the loopback-only service, registers the repository
marketplace, installs the plugin, and opens the Google consent flow. Use
`CODEX=/path/to/codex make install` when the Codex CLI is not on `PATH`.
`make notebooklm-login` opens the separate NotebookLM sign-in flow and stores
its profile under `secrets/notebooklm/`. You can rerun it later to switch or
refresh the NotebookLM account.

Run the checks after installation:

```bash
make check
```

Keep `MW_PROFILE=readonly` until a deliberate test needs write access. Google
and NotebookLM authentication are separate; Maps API access uses its own key.
Every installation supplies its own Google OAuth client, consent-screen name,
and organization audience; no shared OAuth identity is bundled with the repo.
See [docs/setup.md](docs/setup.md) for credential setup, reauthentication,
power mode, and the temporary API-key rollback path.

## Commands

| Command | Use it when |
| --- | --- |
| `make install` | Start, install, and authenticate the local plugin |
| `make up` | Start the service without the Codex install flow |
| `make check` | Run skill-sync checks, tests, and runtime smoke checks |
| `make package` | Build the self-contained plugin archive under `dist/` |
| `make login` | Reconnect the Codex MCP OAuth session |
| `make notebooklm-login` | Authenticate the separate NotebookLM profile |
| `make logs` | Follow service logs |
| `make down` | Stop the local service |

## Architecture and compatibility

This repository owns the 34-tool Workspace runtime, local OAuth bridge,
read/write profile, container, plugin package, and skills. It runs without a
`mythosaur-tools` checkout.

The former handlers and API-key ingress remain temporarily available in
`mythosaur-tools` as rollback paths during the OAuth transition. The
`mythosaur.memory` capability remains in `mythosaur-tools` because it writes
repository-owned memory files and uses its mutation and lifecycle policy.

The normal package uses OAuth and does not include bearer configuration or
secret files. Local credentials and NotebookLM profile state stay under
`secrets/`, which is excluded from Git and plugin packages.

## Project folders

```text
services/   MCP server, authentication, and Workspace handlers
plugins/    Codex plugin metadata and assets
skills/     Workspace routing skill
docs/       Setup and architecture guides
```

## Guides

- [Setup and authentication](docs/setup.md)
- [Architecture and cutover](docs/architecture.md)
- [Skill development and packaging](skills/README.md)
