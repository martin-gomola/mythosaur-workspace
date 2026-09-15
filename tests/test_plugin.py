from __future__ import annotations

import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "mythosaur-workspace"
BUNDLE = json.loads((REPO_ROOT / "plugin-bundle.json").read_text(encoding="utf-8"))


def test_plugin_manifest_and_assets() -> None:
    manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "mythosaur-workspace"
    assert re.fullmatch(r"0\.1\.0\+codex\.\d{14}", manifest["version"])
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert manifest["license"] == "UNLICENSED"
    assert manifest["interface"]["capabilities"] == ["Read", "Write"]
    assert (PLUGIN_ROOT / "assets" / "logo.svg").is_file()
    assert (PLUGIN_ROOT / "assets" / "composer-icon.svg").is_file()


def test_plugin_skills_are_canonical_development_links() -> None:
    actual = {path.name for path in (PLUGIN_ROOT / "skills").iterdir()}
    assert actual == set(BUNDLE["skills"])
    for name in BUNDLE["skills"]:
        link = PLUGIN_ROOT / "skills" / name
        assert link.is_symlink()
        assert link.resolve() == REPO_ROOT / "skills" / "shared" / name


def test_mcp_config_is_workspace_only_and_secret_free() -> None:
    payload = json.loads((PLUGIN_ROOT / ".mcp.json").read_text())
    server = payload["mcpServers"]["mythosaur-workspace"]
    assert server["type"] == "http"
    assert server["url"].endswith("/mcp")
    assert server["enabled"] is True
    assert server["auth"] == "oauth"
    assert "bearer_token_env_var" not in server
    assert server["enabled_tools"] == BUNDLE["enabled_tools"]
    assert len(server["enabled_tools"]) == 34
    assert not {"save_memory", "search_memory"} & set(server["enabled_tools"])
    assert not {"headers", "http_headers", "env_http_headers"} & set(server)


def test_marketplace_points_to_plugin() -> None:
    marketplace = json.loads((REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
    assert marketplace["name"] == "mythosaur-workspace"
    assert marketplace["plugins"] == [
        {
            "name": "mythosaur-workspace",
            "source": {"source": "local", "path": "./plugins/mythosaur-workspace"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }
    ]


def test_skill_names_match_directories() -> None:
    for name in BUNDLE["skills"]:
        text = (REPO_ROOT / "skills" / "shared" / name / "SKILL.md").read_text()
        assert text.startswith("---\n")
        assert f"\nname: {name}\n" in text
        assert "\ndescription:" in text


def test_secret_paths_are_ignored() -> None:
    ignored = (REPO_ROOT / ".gitignore").read_text().splitlines()
    for entry in (
        ".env",
        "secrets/",
        "*.pem",
        "*.key",
        "google-credentials.json",
        "google-token.json",
        "skills/shared/google-workspace-router/references/notebooks.md",
    ):
        assert entry in ignored

    docker_ignored = (REPO_ROOT / ".dockerignore").read_text().splitlines()
    for entry in ("/.git", "/.venv", "/dist", "/secrets", "/shared"):
        assert entry in docker_ignored


def test_packager_writes_self_contained_archive(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "package_plugin.py"),
            "--output",
            str(tmp_path),
            "--version-suffix",
            "test",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    artifact = tmp_path / "mythosaur-workspace-codex-plugin-test.tar.gz"
    assert artifact.is_file()
    assert str(artifact) in result.stdout
    with tarfile.open(artifact, "r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        assert "mythosaur-workspace/.codex-plugin/plugin.json" in names
        assert "mythosaur-workspace/.mcp.json" in names
        for name in BUNDLE["skills"]:
            assert f"mythosaur-workspace/skills/{name}/SKILL.md" in names
        assert "mythosaur-workspace/skills/google-workspace-router/references/notebooks.md.example" in names
        assert "mythosaur-workspace/skills/google-workspace-router/references/notebooks.md" not in names
        assert not any(member.issym() or member.islnk() for member in members)
        assert not any("/tests/" in name for name in names)
        packaged_mcp = json.load(archive.extractfile("mythosaur-workspace/.mcp.json"))
        packaged_server = packaged_mcp["mcpServers"]["mythosaur-workspace"]
        assert packaged_server["auth"] == "oauth"
        assert "bearer_token_env_var" not in packaged_server


def test_local_service_is_loopback_only_and_install_runs_login() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert '127.0.0.1:${MW_MCP_PORT:-8066}:8066' in compose
    for name in (
        "MW_GOOGLE_CALENDAR_WRITE_ENABLED",
        "MW_GOOGLE_GMAIL_SEND_ENABLED",
        "MW_GOOGLE_DRIVE_WRITE_ENABLED",
        "MW_GOOGLE_SHEETS_WRITE_ENABLED",
        "MW_GOOGLE_DOCS_WRITE_ENABLED",
        "MW_GOOGLE_PHOTOS_READ_ENABLED",
        "MW_GOOGLE_PHOTOS_WRITE_ENABLED",
    ):
        assert f"{name}: ${{{name}:-false}}" in compose

    dockerfile = (REPO_ROOT / "services" / "mcp_server" / "Dockerfile").read_text(encoding="utf-8")
    assert '"--no-access-log"' in dockerfile

    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "codex mcp login" not in makefile
    assert "$(CODEX) mcp login mythosaur-workspace" in makefile
    assert '$(CODEX) mcp login mythosaur-workspace --scopes "$$scopes"' in makefile
    assert "--oauth-client-registration" not in makefile
    assert "chmod 600 secrets/google-credentials.json" in makefile


def test_packager_can_build_api_key_rollback_artifact(tmp_path: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "package_plugin.py"),
            "--output",
            str(tmp_path),
            "--version-suffix",
            "rollback",
            "--auth-mode",
            "api_key",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    artifact = tmp_path / "mythosaur-workspace-codex-plugin-rollback.tar.gz"
    with tarfile.open(artifact, "r:gz") as archive:
        packaged_mcp = json.load(archive.extractfile("mythosaur-workspace/.mcp.json"))
    server = packaged_mcp["mcpServers"]["mythosaur-workspace"]
    assert server["bearer_token_env_var"] == "MW_API_KEY"
    assert "auth" not in server
