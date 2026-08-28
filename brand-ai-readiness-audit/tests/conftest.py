"""Shared pytest path setup: unit tests import stage-skill scripts
directly (not via subprocess), so their directories need to be on
sys.path the same way run_audit.py puts them there at runtime."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

for p in [
    REPO_ROOT / "src",
    REPO_ROOT / "skills" / "crawl-reach-audit" / "scripts",
    REPO_ROOT / "skills" / "render-gap-audit" / "scripts",
    REPO_ROOT / "skills" / "extractability-audit" / "scripts",
    REPO_ROOT / "skills" / "retrieval-simulation" / "scripts",
    REPO_ROOT / "skills" / "trust-corroboration-audit" / "scripts",
    REPO_ROOT / "skills" / "arrival-engagement-audit" / "scripts",
]:
    sys.path.insert(0, str(p))
