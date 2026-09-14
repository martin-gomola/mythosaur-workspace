PYTHON ?= python3
PYTEST ?= pytest
UV ?= uv
CODEX ?= codex

.PHONY: check test install login sync-plugin-skills package up down logs google-login notebooklm-login

check:
	@$(UV) run --no-project --with-requirements requirements-dev.txt python scripts/sync_plugin_skills.py --check
	@$(UV) run --no-project --with-requirements requirements-dev.txt pytest -q tests/test_plugin.py tests/runtime/test_oauth.py tests/runtime/test_google_workspace_tools.py tests/runtime/test_notebooklm_tools.py
	@$(UV) run --no-project --with-requirements requirements-dev.txt python tests/runtime_smoke.py
	@git diff --check

test:
	@$(UV) run --no-project --with-requirements requirements-dev.txt pytest -q tests/test_plugin.py tests/runtime/test_oauth.py tests/runtime/test_google_workspace_tools.py tests/runtime/test_notebooklm_tools.py
	@$(UV) run --no-project --with-requirements requirements-dev.txt python tests/runtime_smoke.py

install: sync-plugin-skills
	@command -v docker >/dev/null 2>&1 || { echo "Missing Docker"; exit 1; }
	@command -v curl >/dev/null 2>&1 || { echo "Missing curl"; exit 1; }
	@command -v $(CODEX) >/dev/null 2>&1 || { echo "Missing Codex CLI: $(CODEX)"; exit 1; }
	@test -f secrets/google-credentials.json || { echo "Missing secrets/google-credentials.json"; exit 1; }
	@chmod 700 secrets && chmod 600 secrets/google-credentials.json
	@set -a; [ ! -f .env ] || . ./.env; set +a; [ "$${MW_MCP_AUTH_MODE:-oauth}" = oauth ] || { echo "make install requires MW_MCP_AUTH_MODE=oauth"; exit 1; }
	@docker compose up -d --build
	@set -a; [ ! -f .env ] || . ./.env; set +a; for attempt in $$(seq 1 30); do curl -fsS http://127.0.0.1:$${MW_MCP_PORT:-8066}/healthz >/dev/null && break; [ $$attempt -eq 30 ] && { echo "MCP service did not become ready"; exit 1; }; sleep 1; done
	@case "$$($(CODEX) plugin marketplace list)" in *"$(CURDIR)"*) ;; *) $(CODEX) plugin marketplace add "$(CURDIR)" ;; esac
	@$(CODEX) plugin add mythosaur-workspace@mythosaur-workspace
	@$(MAKE) login PRESET=readonly
	@echo "Installed and authenticated mythosaur-workspace in Codex."
	@echo "Maps API access and NotebookLM use their separate settings in .env."

login:
	@command -v $(CODEX) >/dev/null 2>&1 || { echo "Missing Codex CLI: $(CODEX)"; exit 1; }
	@preset="$${PRESET:-readonly}"; \
	case "$$preset" in readonly) scopes="workspace:read" ;; power) scopes="workspace:read,workspace:write" ;; *) echo "PRESET must be readonly or power"; exit 1 ;; esac; \
	set -a; [ ! -f .env ] || . ./.env; set +a; \
	if [ "$$preset" = power ] && [ "$${MW_PROFILE:-readonly}" != power ]; then echo "Set MW_PROFILE=power and restart the service before power login"; exit 1; fi; \
	$(CODEX) mcp logout mythosaur-workspace >/dev/null 2>&1 || true; \
	$(CODEX) mcp login mythosaur-workspace --oauth-client-registration dcr --scopes "$$scopes"

sync-plugin-skills:
	@$(PYTHON) scripts/sync_plugin_skills.py

package: sync-plugin-skills
	@$(PYTHON) scripts/package_plugin.py --auth-mode "$${AUTH_MODE:-oauth}"

up:
	@docker compose up -d --build

down:
	@docker compose down

logs:
	@docker compose logs -f workspace-mcp

google-login:
	@test -f secrets/google-credentials.json || (echo "Missing secrets/google-credentials.json"; exit 1)
	@mkdir -p secrets
	@$(UV) run --no-project --with-requirements requirements-dev.txt python scripts/auth/google_oauth_bootstrap.py \
		--credentials secrets/google-credentials.json \
		--token secrets/google-token.json \
		--preset "$${PRESET:-readonly}"

notebooklm-login:
	@mkdir -p secrets/notebooklm
	@set -a; [ ! -f .env ] || . ./.env; set +a; \
		NOTEBOOKLM_MCP_CLI_PATH="$(CURDIR)/secrets/notebooklm" \
		$(UV) run --no-project --with-requirements services/mcp_server/requirements.txt \
		python services/mcp_server/notebooklm_cli.py login --profile "$${MW_NOTEBOOKLM_PROFILE:-default}"
