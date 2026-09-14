# Setup

This guide gets Mythosaur Workspace running on your computer. After setup,
Codex can use Google Calendar, Gmail, Drive, Docs, Sheets, Photos, Maps, and
NotebookLM.

The normal setup gives Codex read-only access. It runs the service only on your
computer and keeps your credentials in the local `secrets/` folder.

## Before you start

You need:

- Docker Desktop, installed and running
- `uv` and the Codex CLI
- a Google account
- a copy of this repository on your computer
- a Google Cloud OAuth client for a desktop application

Check that the required tools are ready:

```bash
docker --version
uv --version
codex --version
```

Each command should print a version number. If a command says it was not found,
install that tool before continuing. If Docker cannot connect, open Docker
Desktop and run the check again.

Run all commands below from the repository folder. If you opened a new
terminal, return to that folder first.

## 1. Create your local settings

Copy the example settings file:

```bash
cp .env.example .env
```

Leave this setting as it is:

```text
MW_PROFILE=readonly
```

Read-only mode lets Codex view information without creating, changing, or
sending anything.

## 2. Prepare Google access

Mythosaur Workspace needs its own Google OAuth client. Do not use a credentials
file from another installation.

Most personal installations should use an **External** app. External apps can
be used with any Google account. Choose **Internal** only when every user will
belong to the same company or school Google Workspace organization.

In [Google Cloud Console](https://console.cloud.google.com/):

1. Select an existing Google Cloud project or create one.
2. Enable the Google APIs you plan to use, such as Calendar, Gmail, Drive,
   Docs, Sheets, and Photos.
3. Create an OAuth client ID for a **Desktop app**.
4. Download the client JSON file.

If Google asks you to configure the OAuth consent screen, choose **External**
for a personal Gmail account. Keep the app in **Testing** and add the account
you will use as a test user. Google may show an unverified-app warning during
sign-in. For personal use with fewer than 100 users, Google says verification
is not required, but test-user authorizations expire after seven days.

Put the downloaded file in the repository as:

```text
secrets/google-credentials.json
```

You can move the file there in Finder, or use this command after replacing the
source path with the file's actual location:

```bash
mkdir -p secrets
cp /path/to/downloaded-client.json secrets/google-credentials.json
```

Keep this file private. It is ignored by Git and is not included in plugin
packages.

## 3. Install and sign in

Run:

```bash
make install
```

The command starts the local service, installs the Codex plugin, and opens a
Google sign-in page. The first run may take a few minutes while Docker prepares
the service.

On the Google sign-in page:

1. Choose the Google account whose Calendar, Gmail, Drive, Docs, Sheets, or
   Photos you want to use.
2. Review the requested access.
3. Allow access and return to the terminal.

If the Google Cloud project is restricted to a company or school, choose an
account from that organization. A personal Gmail account will be rejected only
when the app is configured as **Internal**, with an `org_internal` message.

If you see `org_internal` with a personal Gmail account, the OAuth client file
currently belongs to an **Internal** Google Cloud app. Set that app to
**External**, or create a new External Google Cloud project if Google does not
offer that change. Add your Gmail address as a test user, download the new
Desktop app JSON file, replace `secrets/google-credentials.json`, and run
`make login` again.

The installation is complete when the terminal says:

```text
Installed and authenticated mythosaur-workspace in Codex.
```

## 4. Check the installation

Run:

```bash
make check
```

The check is successful when it finishes without an error.

You can now ask Codex to read your Google Workspace data. The service must be
running while you use it. After restarting your computer, start it again with:

```bash
make up
```

## Optional features

### NotebookLM

NotebookLM uses a separate sign-in. To enable it, run:

```bash
make notebooklm-login
```

You may use a different Google account for NotebookLM, for example an account
that has your Gemini subscription. NotebookLM profile data stays in
`secrets/notebooklm/`.

### Google Maps

Maps search and route tools need a Google Maps API key. Add the key to `.env`:

```text
MW_GOOGLE_MAPS_API_KEY=your-key
```

Then restart the service:

```bash
make up
```

Map link-building tools do not need this key.

## Reconnect or fix sign-in

If Codex asks you to sign in again, run:

```bash
make login
```

If Google access was revoked, this command opens the consent page again.

If the Codex browser sign-in cannot be used, the direct Google recovery flow
is:

```bash
make google-login
```

## Allow Codex to make changes

Keep read-only mode unless you deliberately need Codex to create, edit, send,
or upload something. To enable those actions:

1. Open `.env` and change `MW_PROFILE=readonly` to `MW_PROFILE=power`.
2. Restart the service:

   ```bash
   make up
   ```

3. Sign in again with the expanded access:

   ```bash
   make login PRESET=power
   ```

To turn changes off again, set `MW_PROFILE=readonly` in `.env` and run
`make up`. The stored Google credential may still contain permission to write,
but the service will block write tools in read-only mode.

## Sign out

To remove the Codex sign-in for this service, run:

```bash
codex mcp logout mythosaur-workspace
```

Remove `secrets/mcp-oauth-state.json` only if you intentionally want to remove
all locally registered Codex clients and tokens. You will need to run
`make login` again afterwards.

<details>
<summary>Release checks for maintainers</summary>

The following checks belong to release work rather than a normal installation.

Automated transition-release evidence:

- [x] MCP OAuth discovery, DCR, PKCE, resource binding, token rotation,
  revocation, restart persistence, and failure behavior are covered by tests.
- [x] The API-key rollback mode and read-only mutation guard remain covered.
- [x] The service image builds and its OAuth metadata and unauthenticated MCP
  challenge pass inside the built container.
- [x] The normal plugin package contains 34 tools, OAuth configuration, and no
  bearer configuration or secret files.
- [x] `make check`, focused Ruff checks, plugin validation, and the repository
  PII scan pass.

Credential-gated acceptance before the transition release is complete:

- [x] Add `secrets/google-credentials.json` and complete installation/login from a
  logged-out Codex state.
- [ ] Verify real Calendar, Gmail, Drive, Docs, Sheets, and Photos reads.
- [x] Restart the container and confirm Codex remains authenticated and a
  Calendar read succeeds without new consent.
- [ ] Revoke Google access, confirm `reauth_required`, and reconnect.
- [ ] Verify Maps and NotebookLM retain their separate authentication paths.
- [ ] Exercise API-key rollback once with the rollback package.
- [ ] With explicit approval for external writes, verify representative power
  mode mutations and clean up disposable Google artifacts.

After all credential-gated checks pass, the next release removes
`MW_MCP_AUTH_MODE=api_key`, `MW_API_KEY`, `WorkspaceTokenVerifier`, and the
associated rollback tests and documentation. The OAuth migration is not the
finished product until that cleanup release also passes this checklist.

</details>
