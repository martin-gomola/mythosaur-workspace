#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = REPO_ROOT / "plugin-bundle.json"
SHARED_ROOT = REPO_ROOT / "skills" / "shared"
PLUGIN_SKILLS = REPO_ROOT / "plugins" / "mythosaur-workspace" / "skills"


def desired_skills() -> tuple[str, ...]:
    payload = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    skills = payload.get("skills")
    if payload.get("schema_version") != 1 or not isinstance(skills, list) or not skills:
        raise SystemExit("plugin-bundle.json must declare a non-empty schema-v1 skills list")
    if len(skills) != len(set(skills)):
        raise SystemExit("plugin-bundle.json contains duplicate skills")
    for name in skills:
        if not isinstance(name, str) or not (SHARED_ROOT / name / "SKILL.md").is_file():
            raise SystemExit(f"missing shared skill: {name}")
    return tuple(skills)


def expected_target(name: str) -> Path:
    return Path("../../../skills/shared") / name


def check() -> int:
    desired = desired_skills()
    actual = {path.name for path in PLUGIN_SKILLS.iterdir()} if PLUGIN_SKILLS.is_dir() else set()
    if actual != set(desired):
        print(f"plugin skill set differs: expected {sorted(desired)}, found {sorted(actual)}")
        return 1
    for name in desired:
        link = PLUGIN_SKILLS / name
        if not link.is_symlink() or Path(link.readlink()) != expected_target(name):
            print(f"plugin skill link is stale: {name}")
            return 1
    print("plugin skills: clean")
    return 0


def sync() -> int:
    desired = desired_skills()
    PLUGIN_SKILLS.mkdir(parents=True, exist_ok=True)
    for path in PLUGIN_SKILLS.iterdir():
        if path.name in desired and path.is_symlink() and Path(path.readlink()) == expected_target(path.name):
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    for name in desired:
        link = PLUGIN_SKILLS / name
        if not link.exists() and not link.is_symlink():
            link.symlink_to(expected_target(name), target_is_directory=True)
    print("synced plugin skills: " + ", ".join(desired))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return check() if args.check else sync()


if __name__ == "__main__":
    raise SystemExit(main())
