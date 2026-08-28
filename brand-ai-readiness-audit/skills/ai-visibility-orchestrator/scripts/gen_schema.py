#!/usr/bin/env python3
"""Regenerate assets/report_schema.json from src/brand_audit/models.py.

The models are the source of truth -- never hand-edit the generated file.
Run this after any change to models.py:

    python gen_schema.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from brand_audit.models import AuditReport  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = SKILL_DIR / "assets" / "report_schema.json"


def main() -> None:
    schema = AuditReport.model_json_schema()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
