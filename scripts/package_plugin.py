#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "mythosaur-workspace"
PLUGIN_ROOT = REPO_ROOT / "plugins" / PLUGIN_NAME
SHARED_ROOT = REPO_ROOT / "skills" / "shared"
BUNDLE_PATH = REPO_ROOT / "plugin-bundle.json"
DEFAULT_MCP_URL = "http://127.0.0.1:8066/mcp"


def bundle() -> dict:
    return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))


def valid_mcp_url(raw: str) -> str:
    value = raw.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path != "/mcp":
        raise argparse.ArgumentTypeError("MCP URL must be absolute and end with /mcp")
    return value


def short_sha() -> str:
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        if status.stdout.strip():
            return "local"
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "local"
    return result.stdout.strip() or "local"


def ignore_plugin(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in {"skills", ".mcp.json", "__pycache__", ".DS_Store"}}


def copy_skill(source: Path, target: Path) -> None:
    shutil.copytree(
        source,
        target,
        symlinks=False,
        ignore=shutil.ignore_patterns(
            "tests", "__pycache__", "*.pyc", ".DS_Store", "notebooks.md"
        ),
    )


def build_package(package_root: Path, mcp_url: str, auth_mode: str) -> tuple[str, ...]:
    config = bundle()
    skills = tuple(config["skills"])
    shutil.copytree(PLUGIN_ROOT, package_root, symlinks=False, ignore=ignore_plugin)
    skills_root = package_root / "skills"
    skills_root.mkdir()
    for name in skills:
        copy_skill(SHARED_ROOT / name, skills_root / name)
    server = {
        "type": "http",
        "url": mcp_url,
        "enabled": True,
        "enabled_tools": config["enabled_tools"],
    }
    if auth_mode == "oauth":
        server["auth"] = "oauth"
    else:
        server["bearer_token_env_var"] = "MW_API_KEY"
    mcp = {"mcpServers": {PLUGIN_NAME: server}}
    (package_root / ".mcp.json").write_text(json.dumps(mcp, indent=2) + "\n", encoding="utf-8")
    return skills


def validate_package(package_root: Path, skills: tuple[str, ...]) -> None:
    required = [
        package_root / ".codex-plugin" / "plugin.json",
        package_root / ".mcp.json",
        package_root / "assets" / "logo.svg",
        package_root / "assets" / "composer-icon.svg",
        *(package_root / "skills" / name / "SKILL.md" for name in skills),
    ]
    missing = [str(path.relative_to(package_root)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("package is missing: " + ", ".join(missing))
    if any(path.is_symlink() for path in package_root.rglob("*")):
        raise SystemExit("release package must not contain symlinks")
    if any("tests" in path.parts for path in package_root.rglob("*")):
        raise SystemExit("release package must not contain skill tests")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mcp-url",
        type=valid_mcp_url,
        default=valid_mcp_url(os.environ.get("MYTHOSAUR_WORKSPACE_MCP_URL", DEFAULT_MCP_URL)),
    )
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "dist")
    parser.add_argument("--auth-mode", choices=("oauth", "api_key"), default="oauth")
    parser.add_argument("--version-suffix", default=None)
    args = parser.parse_args()

    suffix = (args.version_suffix or short_sha()).strip() or "local"
    args.output.mkdir(parents=True, exist_ok=True)
    artifact = args.output / f"{PLUGIN_NAME}-codex-plugin-{suffix}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="mythosaur-workspace-plugin-") as temporary:
        package_root = Path(temporary) / PLUGIN_NAME
        skills = build_package(package_root, args.mcp_url, args.auth_mode)
        validate_package(package_root, skills)
        with tarfile.open(artifact, "w:gz") as archive:
            archive.add(package_root, arcname=PLUGIN_NAME, recursive=True)
    print(f"wrote {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
