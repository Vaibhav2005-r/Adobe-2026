"""Pydantic v2 models for the audit report.

These models are the single source of truth for the report contract.
`report_schema.json` is generated from them (see scripts/gen_schema.py in
ai-visibility-orchestrator) -- never hand-edit the schema, edit this file
and regenerate.

Every stage skill produces a StageResult; the orchestrator gates, merges,
and assembles them into an AuditReport. See references/composition.md for
the gating contract and references/severity-model.md for how `severity`
is computed (never hand-assigned).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Stage(str, Enum):
    """The six funnel stages a brand can fall out at. Matches the skill
    that owns each stage: crawl-reach-audit, render-gap-audit,
    extractability-audit, retrieval-simulation, trust-corroboration-audit,
    arrival-engagement-audit."""

    REACH = "reach"
    RENDER = "render"
    EXTRACT = "extract"
    RETRIEVE = "retrieve"
    CITE = "cite"
    ARRIVE = "arrive"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReadinessStatus(str, Enum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    SKIPPED = "skipped"


class AnswerabilityOutcome(str, Enum):
    ANSWERABLE = "answerable"
    PARTIAL = "partial"
    UNGROUNDED = "ungrounded"
    UNRETRIEVABLE = "unretrievable"


class Artifact(BaseModel):
    """A machine-checkable proof for a finding. Hard rule: no artifact, no
    finding -- every Finding.artifacts entry must resolve to a live URL a
    reader can re-check."""

    model_config = {"extra": "forbid"}

    url: str
    http_status: int | None = None
    selector: str | None = Field(
        default=None, description="CSS selector or byte-offset locating the evidence"
    )
    html_only_extract: str | None = None
    rendered_extract: str | None = None
    sha256: str | None = None


class Scope(BaseModel):
    """How many pages were checked vs. how many showed the defect. A
    finding can't claim site-wide without this -- see finding-verification's
    sample-adequacy check."""

    model_config = {"extra": "forbid"}

    checked: int = Field(ge=0)
    affected: int = Field(ge=0)
    page_class: str | None = None


class Verification(BaseModel):
    """Output of the falsification pass (finding-verification skill)."""

    model_config = {"extra": "forbid"}

    reproduced: bool
    method: str
    contradicting_signals: list[str] = Field(default_factory=list)


class SuggestedAction(BaseModel):
    model_config = {"extra": "forbid"}

    summary: str
    priority: Severity
    impact: str
    effort: str
    confidence: Confidence
    stage_unblocked: Stage
    implementation: list[str] = Field(default_factory=list)
    verification_step: str | None = Field(
        default=None,
        description="A one-liner the reader can run to confirm the fix worked",
    )
    rationale_ref: str | None = None


class Finding(BaseModel):
    """A single, stage-localized, artifact-backed defect."""

    model_config = {"extra": "forbid"}

    id: str
    title: str
    severity: Severity
    stage: Stage
    taxonomy_id: str = Field(description="e.g. RENDER-001, per references/taxonomy.md")
    scope: Scope
    evidence: str
    artifacts: list[Artifact] = Field(min_length=1)
    confidence: Confidence
    verification: Verification
    impact_mechanism: str = Field(
        description="Why this breaks retrieval/citation -- a mechanism, not a symptom"
    )
    affected_queries: list[str] = Field(default_factory=list)
    suggested_action: SuggestedAction


class StageResult(BaseModel):
    """What every stage skill reads a run_context and writes back. The
    composition contract: retrieval-simulation only ever sees the
    corpus_delta that survived stages (1) reach and (2) render."""

    model_config = {"extra": "forbid"}

    stage: Stage
    findings: list[Finding] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    corpus_delta: list[str] = Field(
        default_factory=list,
        description="URLs this stage added to (or removed from) the AI-reachable corpus",
    )
    metrics: dict[str, float | int | str] = Field(default_factory=dict)


class RunManifest(BaseModel):
    """Determinism proof -- same site in, same report out, modulo audited_at."""

    model_config = {"extra": "forbid"}

    marketplace_version: str
    rule_pack_version: str
    pages_crawled: int = Field(ge=0)
    pages_rendered: int = Field(ge=0)
    sample_seed: str
    duration_s: float = Field(ge=0)
    stages_completed: list[Stage] = Field(default_factory=list)
    degradations: list[str] = Field(
        default_factory=list,
        description="Degradation-ladder steps taken under the 5-minute watchdog, recorded not hidden",
    )


class AIReadiness(BaseModel):
    model_config = {"extra": "forbid"}

    reach: ReadinessStatus
    render: ReadinessStatus
    extract: ReadinessStatus
    retrieve: ReadinessStatus
    cite: ReadinessStatus
    arrive: ReadinessStatus


class AnswerabilitySummary(BaseModel):
    model_config = {"extra": "forbid"}

    answerable: int = Field(ge=0, default=0)
    partial: int = Field(ge=0, default=0)
    ungrounded: int = Field(ge=0, default=0)
    unretrievable: int = Field(ge=0, default=0)


class Summary(BaseModel):
    model_config = {"extra": "forbid"}

    total_findings: int = Field(ge=0)
    critical: int = Field(ge=0)
    high: int = Field(ge=0)
    medium: int = Field(ge=0)
    low: int = Field(ge=0)
    ai_readiness: AIReadiness
    answerability: AnswerabilitySummary
    headline: str


class AnswerabilityMatrixEntry(BaseModel):
    model_config = {"extra": "forbid"}

    query: str
    intent: str
    outcome: AnswerabilityOutcome
    top_chunk_url: str | None = None
    citable: bool
    top_chunk_position_ratio: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "How far into the page's main content the cited chunk sits (0.0 = "
            "start, 1.0 = end). Lets stage (6) ARRIVE ask 'is the citable "
            "answer above the fold' without re-deriving chunk positions from "
            "scratch -- retrieval-simulation already computes this once."
        ),
    )


class ProactiveRecommendation(BaseModel):
    model_config = {"extra": "forbid"}

    title: str
    rationale: str = Field(description="What measured gap this is derived from -- not a static list item")
    suggested_action: SuggestedAction | None = None


class AuditReport(BaseModel):
    """The single validated report the orchestrator assembles. Superset of
    the required floor: site, audited_at, summary, and per-finding id/
    title/severity/evidence/suggested_action."""

    model_config = {"extra": "forbid"}

    site: str
    audited_at: datetime
    schema_version: str = "1.0.0"
    run_manifest: RunManifest
    summary: Summary
    findings: list[Finding] = Field(default_factory=list)
    observations: list[Finding] = Field(
        default_factory=list,
        description="Findings that failed falsification -- demoted, never silently dropped",
    )
    proactive_recommendations: list[ProactiveRecommendation] = Field(default_factory=list)
    answerability_matrix: list[AnswerabilityMatrixEntry] = Field(default_factory=list)
