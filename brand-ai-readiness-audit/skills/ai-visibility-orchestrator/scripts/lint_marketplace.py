#!/usr/bin/env python3
"""Manifest lint: marketplace.json must be valid, list every skill folder
that actually exists, list none that don't, and declare exactly one
entrypoint that itself exists among the listed skills.

Exit 0 / prints "OK" on success. Exit 1 with a message per problem
otherwise -- this is what CI runs alongside `skills-ref validate`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # brand-ai-readiness-audit/
MANIFEST_PATH = ROOT / "marketplace.json"
SKILLS_DIR = ROOT / "skills"


def main() -> int:
    errors: list[str] = []

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"error: {MANIFEST_PATH} not found")
        return 1
    except json.JSONDecodeError as exc:
        print(f"error: {MANIFEST_PATH} is not valid JSON: {exc}")
        return 1

    plugins = manifest.get("plugins", [])
    if len(plugins) != 1:
        errors.append(f"expected exactly 1 plugin entry, found {len(plugins)}")

    entrypoint = manifest.get("metadata", {}).get("entrypoint")
    if not entrypoint:
        errors.append("metadata.entrypoint is not set")

    actual_skill_dirs = {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()}

    listed_skill_names: set[str] = set()
    if plugins:
        for skill_path in plugins[0].get("skills", []):
            name = Path(skill_path).name
            listed_skill_names.add(name)
            if name not in actual_skill_dirs:
                errors.append(f"marketplace.json lists '{skill_path}' but skills/{name}/ does not exist")
            skill_md = SKILLS_DIR / name / "SKILL.md"
            if not skill_md.exists():
                errors.append(f"skills/{name}/SKILL.md does not exist")

    missing_from_manifest = actual_skill_dirs - listed_skill_names
    if missing_from_manifest:
        errors.append(f"skill folders not listed in marketplace.json: {sorted(missing_from_manifest)}")

    if entrypoint and entrypoint not in listed_skill_names:
        errors.append(f"metadata.entrypoint '{entrypoint}' is not among the listed skills")

    if entrypoint and entrypoint not in actual_skill_dirs:
        errors.append(f"metadata.entrypoint '{entrypoint}' does not exist under skills/")

    if errors:
        print(f"Manifest lint failed for {MANIFEST_PATH}:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"OK: {MANIFEST_PATH} -- {len(actual_skill_dirs)} skills, entrypoint '{entrypoint}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
