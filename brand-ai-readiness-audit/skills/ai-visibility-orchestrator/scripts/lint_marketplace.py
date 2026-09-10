#!/usr/bin/env python3
"""Manifest lint against the shape the Round 3 handout specifies.

The handout is explicit that this is the contest's own convention, not
an external standard: "agentskills.io defines the single-skill SKILL.md
format but does not define a multi-skill marketplace format -- the
manifest below is this contest's own lightweight convention." So the
handout's own example is the spec, verbatim:

    {
      "name": "brand-ai-readiness-audit",
      "version": "1.0.0",
      "skills": [
        { "id": "audit-orchestrator", "path": "skills/audit-orchestrator", "entrypoint": true },
        { "id": "crawl-render-audit", "path": "skills/crawl-render-audit" }
      ]
    }

Requirements this enforces, each traceable to a line in the handout:

- `marketplace.json` sits at the marketplace root ("The marketplace root
  must include a top-level manifest, marketplace.json").
- It lists every skill ("listing every skill").
- Exactly one skill carries `entrypoint: true` ("marking exactly one as
  the entrypoint"), and no other value of `entrypoint` counts.
- Every listed `path` exists and contains a `SKILL.md` ("Every skill
  folder listed in the marketplace must contain a valid SKILL.md").
- No skill folder on disk is missing from the manifest -- the mirror of
  "listing every skill", and the failure mode that actually happens when
  a stage is added.
- Nothing in the manifest points outside the marketplace root, since the
  handout requires the manifest be "self-contained -- no external service
  needed to resolve it".

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

_ALLOWED_TOP_LEVEL = {"name", "version", "skills"}
_ALLOWED_SKILL_KEYS = {"id", "path", "entrypoint"}


def main() -> int:
    errors: list[str] = []

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Manifest lint failed:\n  - {MANIFEST_PATH.name} not found at the marketplace root")
        return 1
    except json.JSONDecodeError as exc:
        print(f"Manifest lint failed:\n  - marketplace.json is not valid JSON: {exc}")
        return 1

    for required in ("name", "version", "skills"):
        if required not in manifest:
            errors.append(f"marketplace.json: missing required top-level field '{required}'")

    # Kept closed on purpose. The handout gives an exact object rather than
    # a floor (unlike the report schema, which it explicitly calls "a floor,
    # not a ceiling"), so an unrecognised key here is a drift signal, not an
    # extension.
    extra = set(manifest) - _ALLOWED_TOP_LEVEL
    if extra:
        errors.append(
            f"marketplace.json: unexpected top-level key(s) {sorted(extra)} "
            f"-- the handout's manifest is exactly {sorted(_ALLOWED_TOP_LEVEL)}"
        )

    skills = manifest.get("skills", [])
    if not isinstance(skills, list) or not skills:
        errors.append("marketplace.json: 'skills' must be a non-empty list")
        skills = []

    listed_ids: list[str] = []
    entrypoints: list[str] = []
    for i, entry in enumerate(skills):
        if not isinstance(entry, dict):
            errors.append(f"marketplace.json: skills[{i}] is not an object")
            continue
        unexpected = set(entry) - _ALLOWED_SKILL_KEYS
        if unexpected:
            errors.append(f"marketplace.json: skills[{i}] has unexpected key(s) {sorted(unexpected)}")

        skill_id = entry.get("id")
        path = entry.get("path")
        if not skill_id:
            errors.append(f"marketplace.json: skills[{i}] is missing 'id'")
        if not path:
            errors.append(f"marketplace.json: skills[{i}] is missing 'path'")
            continue

        listed_ids.append(skill_id)
        if entry.get("entrypoint") is True:
            entrypoints.append(skill_id)

        # Self-contained: no absolute paths, no traversal out of the root.
        if Path(path).is_absolute() or ".." in Path(path).parts:
            errors.append(f"marketplace.json: skills[{i}] path '{path}' escapes the marketplace root")
            continue

        folder = ROOT / path
        if not folder.is_dir():
            errors.append(f"marketplace.json: skills[{i}] path '{path}' does not exist")
        elif not (folder / "SKILL.md").is_file():
            errors.append(f"{path}/SKILL.md does not exist")
        elif skill_id and folder.name != skill_id:
            # `skills-ref` requires SKILL.md's `name` to match its folder,
            # so an id that disagrees with the folder makes the manifest and
            # the skill disagree about what the skill is called.
            errors.append(f"marketplace.json: skills[{i}] id '{skill_id}' does not match folder '{folder.name}'")

    if len(entrypoints) != 1:
        errors.append(
            f"marketplace.json: exactly one skill must have \"entrypoint\": true, found {len(entrypoints)}"
            + (f" ({entrypoints})" if entrypoints else "")
        )

    on_disk = {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()} if SKILLS_DIR.is_dir() else set()
    missing = on_disk - set(listed_ids)
    if missing:
        errors.append(f"skill folders present on disk but not listed in marketplace.json: {sorted(missing)}")

    if errors:
        print("Manifest lint failed:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(
        f"OK: marketplace.json -- {len(listed_ids)} skills, "
        f"exactly one entrypoint ('{entrypoints[0]}'), every path resolves inside the marketplace root"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
