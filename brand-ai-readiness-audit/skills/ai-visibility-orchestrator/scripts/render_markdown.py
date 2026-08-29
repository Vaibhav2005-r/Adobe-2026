"""Markdown executive summary (docs/build-plan.md Part 3 / Day 8 DoD).
Deliberately terser than the HTML report: a non-expert reads this one
top to bottom in under a minute -- headline, funnel status, findings by
stage (title + one-line evidence, not the full artifact dump), and the
prioritized action list. The HTML report is where every artifact,
extract, and implementation step lives; this is the "read this first"
surface, not a second full copy of the same data.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from brand_audit.models import AuditReport, ReadinessStatus, Severity, Stage  # noqa: E402

_FUNNEL_ORDER = [Stage.REACH, Stage.RENDER, Stage.EXTRACT, Stage.RETRIEVE, Stage.CITE, Stage.ARRIVE]
_STAGE_LABELS = {
    Stage.REACH: "① REACH", Stage.RENDER: "② RENDER", Stage.EXTRACT: "③ EXTRACT",
    Stage.RETRIEVE: "④ RETRIEVE", Stage.CITE: "⑤ CITE", Stage.ARRIVE: "⑥ ARRIVE",
}
_READINESS_ICON = {
    ReadinessStatus.PASS: "✅ pass", ReadinessStatus.PARTIAL: "⚠️ partial",
    ReadinessStatus.FAIL: "❌ fail", ReadinessStatus.SKIPPED: "⏭️ skipped",
}
_SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


def _md_escape(value) -> str:
    """Escape the handful of Markdown-active characters most likely to
    appear in site-derived text (evidence, titles) and break table
    layout or accidentally create emphasis/links -- not a full
    CommonMark-escaping pass, just enough to keep a report table from
    visibly breaking on a pipe or bracket character pulled from a real
    page."""
    text = str(value)
    for ch in ("\\", "|", "*", "_", "[", "]"):
        text = text.replace(ch, "\\" + ch)
    return text.replace("\n", " ")


def _funnel_table(report: AuditReport) -> str:
    fields = {
        Stage.REACH: report.summary.ai_readiness.reach, Stage.RENDER: report.summary.ai_readiness.render,
        Stage.EXTRACT: report.summary.ai_readiness.extract, Stage.RETRIEVE: report.summary.ai_readiness.retrieve,
        Stage.CITE: report.summary.ai_readiness.cite, Stage.ARRIVE: report.summary.ai_readiness.arrive,
    }
    header = "| " + " | ".join(_STAGE_LABELS[s] for s in _FUNNEL_ORDER) + " |"
    sep = "|" + "---|" * len(_FUNNEL_ORDER)
    row = "| " + " | ".join(_READINESS_ICON[fields[s]] for s in _FUNNEL_ORDER) + " |"
    return f"{header}\n{sep}\n{row}\n"


def _findings_section(report: AuditReport) -> str:
    lines = []
    for stage in _FUNNEL_ORDER:
        stage_findings = sorted(
            (f for f in report.findings if f.stage == stage), key=lambda f: _SEVERITY_RANK[f.severity]
        )
        if not stage_findings:
            continue
        lines.append(f"### {_STAGE_LABELS[stage]}\n")
        for f in stage_findings:
            lines.append(
                f"- **[{f.severity.value.upper()}] {_md_escape(f.title)}** (`{f.taxonomy_id}`, "
                f"confidence: {f.confidence.value}, checked {f.scope.checked}/affected {f.scope.affected})"
            )
        lines.append("")
    return "\n".join(lines) if lines else "No findings on the stages that ran.\n"


def _action_list(report: AuditReport) -> str:
    actionable = sorted(report.findings, key=lambda f: _SEVERITY_RANK[f.severity])[:10]
    if not actionable:
        return "No prioritized actions -- no findings.\n"
    lines = []
    for i, f in enumerate(actionable, 1):
        a = f.suggested_action
        lines.append(
            f"{i}. **[{f.severity.value.upper()}]** {_md_escape(a.summary)} "
            f"_(unblocks {a.stage_unblocked.value}, impact: {a.impact}, effort: {a.effort})_"
        )
    return "\n".join(lines) + "\n"


def render_markdown_summary(report: AuditReport) -> str:
    s = report.summary
    observations_note = (
        f"\n{len(report.observations)} additional candidate(s) did not pass falsification and are "
        f"held as observations in the full JSON/HTML report, not shown here.\n"
        if report.observations
        else ""
    )
    degradations_note = (
        "\n**Degradations recorded this run:** " + ", ".join(f"`{d}`" for d in report.run_manifest.degradations) + "\n"
        if report.run_manifest.degradations
        else ""
    )
    return f"""# AI Visibility Audit — {_md_escape(report.site)}

**{_md_escape(s.headline)}**

Audited {report.audited_at} · {report.run_manifest.pages_crawled} pages crawled, {report.run_manifest.pages_rendered} rendered · {report.run_manifest.duration_s:.1f}s

## Funnel status

{_funnel_table(report)}
## Summary

| Critical | High | Medium | Low | Total |
|---|---|---|---|---|
| {s.critical} | {s.high} | {s.medium} | {s.low} | {s.total_findings} |

Answerability: {s.answerability.answerable} answerable, {s.answerability.partial} partial, {s.answerability.ungrounded} ungrounded, {s.answerability.unretrievable} unretrievable (of {len(report.answerability_matrix)} simulated buyer-intent queries).
{observations_note}
## Prioritized action list

{_action_list(report)}
## Findings by stage

{_findings_section(report)}
{degradations_note}
---
_Full evidence, artifacts, and implementation steps for every finding are in the accompanying JSON and HTML reports._
"""


def render_markdown_summary_from_json(json_path: str) -> str:
    data = Path(json_path).read_text(encoding="utf-8")
    report = AuditReport.model_validate_json(data)
    return render_markdown_summary(report)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: render_markdown.py <report.json> <out.md>", file=sys.stderr)
        raise SystemExit(2)
    md_out = render_markdown_summary_from_json(sys.argv[1])
    Path(sys.argv[2]).write_text(md_out, encoding="utf-8")
    print(f"Wrote {sys.argv[2]}")
