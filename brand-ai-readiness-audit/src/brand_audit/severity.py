"""Deterministic severity: severity = f(stage, blast_radius, confidence).

Implements the decision table in
skills/ai-visibility-orchestrator/references/severity-model.md. A
detector reports what it observed (stage, blast radius, confidence);
this function is the only place that turns that into a Severity --
detectors never hand-assign one.
"""

from __future__ import annotations

from enum import Enum

from .models import Confidence, Severity, Stage


class BlastRadius(str, Enum):
    SITE_WIDE = "site_wide"
    PAGE_CLASS = "page_class"
    DEGRADES = "degrades"
    NONE = "none"


def compute_severity(stage: Stage, blast_radius: BlastRadius, confidence: Confidence) -> Severity:
    if blast_radius == BlastRadius.SITE_WIDE and stage in (Stage.REACH, Stage.RENDER):
        base = Severity.CRITICAL
    elif blast_radius == BlastRadius.PAGE_CLASS:
        base = Severity.HIGH
    elif blast_radius == BlastRadius.DEGRADES:
        base = Severity.MEDIUM
    else:
        base = Severity.LOW

    # Confidence only ever discounts severity, never inflates it -- see
    # severity-model.md. Low-confidence candidates are expected to be
    # demoted to observations by the caller rather than shipped as
    # findings at all; this clamp is a backstop in case one slips through.
    if confidence == Confidence.LOW and base in (Severity.CRITICAL, Severity.HIGH):
        return Severity.MEDIUM
    return base
