"""Single-file HTML report -- the demo surface (docs/build-plan.md Part
2 (8), Day 8 DoD). Funnel diagram with the failing stage highlighted,
findings grouped by stage, the answerability matrix, and a prioritized
action list, all in one self-contained HTML file: inline CSS, no
external assets, no CDN, no JS framework -- a judge on a bare, offline
machine can open it directly in a browser.

Security note: every string embedded here can originate from the
*audited site* (evidence, extracted strings, entity names, titles) --
this is untrusted content being written into an HTML document a human
will open in a real browser. Everything goes through `_esc()`
(`html.escape`) before insertion; URLs additionally go through
`_safe_link()`, which only emits a clickable `<a href>` for http(s)
schemes and otherwise falls back to escaped plain text -- a
`javascript:`-scheme "URL" embedded in a page's own extracted text
(or a manipulated report.json) can't become a clickable link this way.
"""

from __future__ import annotations

import html as html_lib
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from brand_audit.models import (  # noqa: E402
    AuditReport,
    Finding,
    ReadinessStatus,
    Severity,
    Stage,
)

_FUNNEL_ORDER = [Stage.REACH, Stage.RENDER, Stage.EXTRACT, Stage.RETRIEVE, Stage.CITE, Stage.ARRIVE]
_STAGE_LABELS = {
    Stage.REACH: "① REACH", Stage.RENDER: "② RENDER", Stage.EXTRACT: "③ EXTRACT",
    Stage.RETRIEVE: "④ RETRIEVE", Stage.CITE: "⑤ CITE", Stage.ARRIVE: "⑥ ARRIVE",
}
_READINESS_LABEL = {
    ReadinessStatus.PASS: "pass", ReadinessStatus.PARTIAL: "partial",
    ReadinessStatus.FAIL: "fail", ReadinessStatus.SKIPPED: "skipped",
}
_SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


def _esc(value) -> str:
    return html_lib.escape(str(value), quote=True)


def _safe_link(url: str) -> str:
    try:
        scheme = urlparse(url).scheme.lower()
    except ValueError:
        return _esc(url)
    if scheme not in ("http", "https"):
        return _esc(url)
    escaped = _esc(url)
    return f'<a href="{escaped}" target="_blank" rel="noopener noreferrer">{escaped}</a>'


def _readiness_for_first_failure(report: AuditReport) -> Stage | None:
    """The exact stage where the brand first falls out -- the whole
    thesis in one value. FAIL beats PARTIAL; the earliest funnel stage
    with either wins, since a downstream partial doesn't matter if an
    upstream stage already fails outright."""
    fields = {
        Stage.REACH: report.summary.ai_readiness.reach, Stage.RENDER: report.summary.ai_readiness.render,
        Stage.EXTRACT: report.summary.ai_readiness.extract, Stage.RETRIEVE: report.summary.ai_readiness.retrieve,
        Stage.CITE: report.summary.ai_readiness.cite, Stage.ARRIVE: report.summary.ai_readiness.arrive,
    }
    for stage in _FUNNEL_ORDER:
        if fields[stage] == ReadinessStatus.FAIL:
            return stage
    for stage in _FUNNEL_ORDER:
        if fields[stage] == ReadinessStatus.PARTIAL:
            return stage
    return None


def _funnel_html(report: AuditReport) -> str:
    fields = {
        Stage.REACH: report.summary.ai_readiness.reach, Stage.RENDER: report.summary.ai_readiness.render,
        Stage.EXTRACT: report.summary.ai_readiness.extract, Stage.RETRIEVE: report.summary.ai_readiness.retrieve,
        Stage.CITE: report.summary.ai_readiness.cite, Stage.ARRIVE: report.summary.ai_readiness.arrive,
    }
    first_failure = _readiness_for_first_failure(report)
    boxes = []
    for i, stage in enumerate(_FUNNEL_ORDER):
        status = fields[stage]
        highlight = " funnel-box-highlight" if stage == first_failure else ""
        boxes.append(
            f'<div class="funnel-box funnel-status-{status.value}{highlight}">'
            f'<div class="funnel-label">{_esc(_STAGE_LABELS[stage])}</div>'
            f'<div class="funnel-status">{_esc(_READINESS_LABEL[status])}</div>'
            f"</div>"
        )
        if i < len(_FUNNEL_ORDER) - 1:
            boxes.append('<div class="funnel-arrow">&rarr;</div>')
    return f'<div class="funnel">{"".join(boxes)}</div>'


def _artifact_html(artifact) -> str:
    parts = [f'<div class="artifact">{_safe_link(artifact.url)}']
    if artifact.http_status is not None:
        parts.append(f'<span class="artifact-meta">HTTP {_esc(artifact.http_status)}</span>')
    if artifact.selector:
        parts.append(f'<div class="artifact-selector"><code>{_esc(artifact.selector)}</code></div>')
    if artifact.html_only_extract:
        parts.append(
            f'<details class="artifact-extract"><summary>HTML-only extract</summary>'
            f"<pre>{_esc(artifact.html_only_extract)}</pre></details>"
        )
    if artifact.rendered_extract:
        parts.append(
            f'<details class="artifact-extract"><summary>Rendered extract</summary>'
            f"<pre>{_esc(artifact.rendered_extract)}</pre></details>"
        )
    parts.append("</div>")
    return "".join(parts)


def _finding_html(finding: Finding) -> str:
    artifacts_html = "".join(_artifact_html(a) for a in finding.artifacts)
    queries_html = ""
    if finding.affected_queries:
        items = "".join(f"<li>{_esc(q)}</li>" for q in finding.affected_queries[:10])
        queries_html = f'<div class="finding-section"><strong>Affected queries</strong><ul>{items}</ul></div>'
    contradictions_html = ""
    if finding.verification.contradicting_signals:
        items = "".join(f"<li>{_esc(s)}</li>" for s in finding.verification.contradicting_signals)
        contradictions_html = (
            f'<div class="finding-section"><strong>Contradicting signals</strong><ul>{items}</ul></div>'
        )
    action = finding.suggested_action
    impl_items = "".join(f"<li>{_esc(step)}</li>" for step in action.implementation)
    verification_step_html = (
        f'<div class="verification-step"><strong>Verify the fix:</strong> <code>{_esc(action.verification_step)}</code></div>'
        if action.verification_step
        else ""
    )
    return f"""
<div class="finding severity-{finding.severity.value}">
  <div class="finding-header">
    <span class="badge badge-severity-{finding.severity.value}">{_esc(finding.severity.value)}</span>
    <span class="badge badge-taxonomy">{_esc(finding.taxonomy_id)}</span>
    <span class="badge badge-confidence">confidence: {_esc(finding.confidence.value)}</span>
    <span class="badge badge-reproduced-{str(finding.verification.reproduced).lower()}">
      {"reproduced" if finding.verification.reproduced else "not re-verified"}
    </span>
  </div>
  <h3 class="finding-title">{_esc(finding.title)}</h3>
  <div class="finding-section"><strong>Evidence</strong><p>{_esc(finding.evidence)}</p></div>
  <div class="finding-section"><strong>Why this breaks retrieval/citation</strong><p>{_esc(finding.impact_mechanism)}</p></div>
  <div class="finding-section"><strong>Scope</strong><p>checked {_esc(finding.scope.checked)}, affected {_esc(finding.scope.affected)}{f", page class {_esc(finding.scope.page_class)}" if finding.scope.page_class else ""}</p></div>
  {queries_html}
  {contradictions_html}
  <div class="finding-section"><strong>Artifacts</strong>{artifacts_html}</div>
  <div class="suggested-action">
    <strong>Suggested action</strong> (impact: {_esc(action.impact)}, effort: {_esc(action.effort)})
    <p>{_esc(action.summary)}</p>
    {f"<ul>{impl_items}</ul>" if impl_items else ""}
    {verification_step_html}
  </div>
</div>
""".strip()


def _findings_by_stage_html(report: AuditReport) -> str:
    sections = []
    for stage in _FUNNEL_ORDER:
        stage_findings = sorted(
            (f for f in report.findings if f.stage == stage), key=lambda f: _SEVERITY_RANK[f.severity]
        )
        if not stage_findings:
            continue
        cards = "".join(_finding_html(f) for f in stage_findings)
        sections.append(
            f'<section class="stage-section"><h2>{_esc(_STAGE_LABELS[stage])} '
            f"&mdash; {len(stage_findings)} finding{'s' if len(stage_findings) != 1 else ''}</h2>{cards}</section>"
        )
    if not sections:
        return '<p class="empty-state">No findings on the stages that ran.</p>'
    return "".join(sections)


def _observations_html(report: AuditReport) -> str:
    if not report.observations:
        return ""
    cards = "".join(_finding_html(f) for f in report.observations)
    return f"""
<section class="stage-section observations-section">
  <h2>Observations &mdash; did not pass falsification</h2>
  <p class="observations-note">
    These candidates failed finding-verification's falsification pass (re-fetch,
    sample-adequacy, or contradiction check) and are shown here, not silently
    dropped, per the audit's own epistemic-discipline rule.
  </p>
  {cards}
</section>
""".strip()


def _answerability_matrix_html(report: AuditReport) -> str:
    if not report.answerability_matrix:
        return ""
    rows = []
    for entry in report.answerability_matrix:
        ratio = f"{entry.top_chunk_position_ratio:.0%}" if entry.top_chunk_position_ratio is not None else "&mdash;"
        rows.append(
            f"<tr class='outcome-{entry.outcome.value}'>"
            f"<td>{_esc(entry.intent)}</td><td>{_esc(entry.query)}</td>"
            f"<td>{_esc(entry.outcome.value)}</td>"
            f"<td>{_safe_link(entry.top_chunk_url) if entry.top_chunk_url else '&mdash;'}</td>"
            f"<td>{ratio}</td></tr>"
        )
    a = report.summary.answerability
    return f"""
<section class="stage-section">
  <h2>Answerability matrix</h2>
  <p>{a.answerable} answerable &middot; {a.partial} partial &middot; {a.ungrounded} ungrounded &middot; {a.unretrievable} unretrievable</p>
  <div class="table-scroll">
  <table class="matrix-table">
    <thead><tr><th>Intent</th><th>Query</th><th>Outcome</th><th>Top chunk</th><th>Position</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
  </div>
</section>
""".strip()


def _action_list_html(report: AuditReport) -> str:
    actionable = sorted(report.findings, key=lambda f: _SEVERITY_RANK[f.severity])
    if not actionable:
        return ""
    items = []
    for f in actionable[:15]:
        items.append(
            f"<li><span class='badge badge-severity-{f.severity.value}'>{_esc(f.severity.value)}</span> "
            f"<strong>{_esc(f.suggested_action.summary)}</strong> "
            f"<span class='action-meta'>(unblocks {_esc(f.suggested_action.stage_unblocked.value)}, "
            f"impact: {_esc(f.suggested_action.impact)}, effort: {_esc(f.suggested_action.effort)})</span></li>"
        )
    return f"""
<section class="stage-section">
  <h2>Prioritized action list</h2>
  <ol class="action-list">{"".join(items)}</ol>
</section>
""".strip()


def _manifest_html(report: AuditReport) -> str:
    m = report.run_manifest
    degradations_html = (
        f"<ul>{''.join(f'<li>{_esc(d)}</li>' for d in m.degradations)}</ul>" if m.degradations else "<p>none</p>"
    )
    return f"""
<footer class="run-manifest">
  <h2>Run manifest</h2>
  <p>
    marketplace {_esc(m.marketplace_version)} &middot; rule pack {_esc(m.rule_pack_version)} &middot;
    {_esc(m.pages_crawled)} pages crawled, {_esc(m.pages_rendered)} rendered &middot;
    {m.duration_s:.1f}s &middot; seed {_esc(m.sample_seed)}
  </p>
  <p>stages completed: {_esc(', '.join(s.value for s in m.stages_completed))}</p>
  <details><summary>Degradations</summary>{degradations_html}</details>
</footer>
""".strip()


_STYLE = """
:root {
  --bg: #ffffff; --fg: #1a1a1a; --muted: #666666; --border: #dddddd;
  --card-bg: #fafafa; --code-bg: #f0f0f0;
  --critical: #b3261e; --high: #c05621; --medium: #9a7d0a; --low: #4a5568;
  --pass: #1e7e34; --partial: #9a7d0a; --fail: #b3261e; --skipped: #888888;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14161a; --fg: #e8e8e8; --muted: #a0a0a0; --border: #333844;
    --card-bg: #1c1f26; --code-bg: #23262e;
    --critical: #ff6b60; --high: #ff9d5c; --medium: #f0cf5c; --low: #9fb0c3;
    --pass: #6fcf7a; --partial: #f0cf5c; --fail: #ff6b60; --skipped: #999999;
  }
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--fg); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.5; margin: 0; padding: 2rem 1rem 4rem;
}
.report { max-width: 900px; margin: 0 auto; }
h1 { font-size: 1.6rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.2rem; margin-top: 2.5rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4rem; }
h3.finding-title { font-size: 1.05rem; margin: 0.6rem 0; }
.headline { font-size: 1.1rem; color: var(--muted); margin: 0.5rem 0 1.5rem; }
.meta { color: var(--muted); font-size: 0.9rem; }
.funnel { display: flex; align-items: center; flex-wrap: wrap; gap: 0.25rem; margin: 1.5rem 0; }
.funnel-box {
  border: 1px solid var(--border); border-radius: 8px; padding: 0.6rem 0.9rem; text-align: center; min-width: 90px;
  background: var(--card-bg);
}
.funnel-box-highlight { border-width: 3px; border-color: var(--fail); }
.funnel-label { font-size: 0.8rem; font-weight: 600; }
.funnel-status { font-size: 0.75rem; text-transform: uppercase; margin-top: 0.15rem; }
.funnel-status-pass .funnel-status { color: var(--pass); }
.funnel-status-partial .funnel-status { color: var(--partial); }
.funnel-status-fail .funnel-status { color: var(--fail); }
.funnel-status-skipped .funnel-status { color: var(--skipped); }
.funnel-arrow { color: var(--muted); }
.summary-stats { display: flex; gap: 1.5rem; flex-wrap: wrap; margin: 1rem 0 2rem; }
.stat { text-align: center; }
.stat-value { font-size: 1.6rem; font-weight: 700; display: block; }
.stat-label { font-size: 0.8rem; color: var(--muted); text-transform: uppercase; }
.stat-critical .stat-value { color: var(--critical); }
.stat-high .stat-value { color: var(--high); }
.stat-medium .stat-value { color: var(--medium); }
.stat-low .stat-value { color: var(--low); }
.finding {
  border: 1px solid var(--border); border-left-width: 5px; border-radius: 6px; padding: 1rem 1.2rem;
  margin: 1rem 0; background: var(--card-bg);
}
.finding.severity-critical { border-left-color: var(--critical); }
.finding.severity-high { border-left-color: var(--high); }
.finding.severity-medium { border-left-color: var(--medium); }
.finding.severity-low { border-left-color: var(--low); }
.finding-header { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-bottom: 0.3rem; }
.badge {
  display: inline-block; font-size: 0.72rem; padding: 0.15rem 0.5rem; border-radius: 999px;
  border: 1px solid var(--border); text-transform: uppercase; letter-spacing: 0.02em; color: var(--muted);
}
.badge-severity-critical { color: var(--critical); border-color: var(--critical); }
.badge-severity-high { color: var(--high); border-color: var(--high); }
.badge-severity-medium { color: var(--medium); border-color: var(--medium); }
.badge-severity-low { color: var(--low); border-color: var(--low); }
.badge-reproduced-true { color: var(--pass); border-color: var(--pass); }
.badge-reproduced-false { color: var(--fail); border-color: var(--fail); }
.finding-section { margin: 0.6rem 0; }
.finding-section p { margin: 0.2rem 0; }
.artifact { border: 1px solid var(--border); border-radius: 4px; padding: 0.5rem 0.7rem; margin: 0.4rem 0; font-size: 0.85rem; }
.artifact-meta { color: var(--muted); margin-left: 0.5rem; }
.artifact-selector { margin-top: 0.3rem; }
code { background: var(--code-bg); padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.85em; word-break: break-word; }
pre {
  background: var(--code-bg); padding: 0.6rem; border-radius: 4px; overflow-x: auto; font-size: 0.8rem;
  white-space: pre-wrap; word-break: break-word;
}
.suggested-action { margin-top: 0.8rem; padding-top: 0.6rem; border-top: 1px dashed var(--border); }
.verification-step { margin-top: 0.4rem; font-size: 0.9rem; }
.observations-note { color: var(--muted); font-size: 0.9rem; }
.table-scroll { overflow-x: auto; }
table.matrix-table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
table.matrix-table th, table.matrix-table td { border-bottom: 1px solid var(--border); padding: 0.4rem 0.6rem; text-align: left; }
tr.outcome-answerable td:nth-child(3) { color: var(--pass); }
tr.outcome-partial td:nth-child(3) { color: var(--partial); }
tr.outcome-ungrounded td:nth-child(3), tr.outcome-unretrievable td:nth-child(3) { color: var(--fail); }
.action-list li { margin: 0.5rem 0; }
.action-meta { color: var(--muted); font-size: 0.85rem; }
.run-manifest { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.85rem; }
.empty-state { color: var(--muted); }
a { color: inherit; }
"""


def render_html_report(report: AuditReport) -> str:
    first_failure = _readiness_for_first_failure(report)
    first_failure_note = (
        f"<p class='meta'>First funnel stage the brand falls out at: <strong>{_esc(_STAGE_LABELS[first_failure])}</strong></p>"
        if first_failure is not None
        else "<p class='meta'>No stage fails outright on the pages sampled.</p>"
    )
    s = report.summary
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AI readiness audit -- {_esc(report.site)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{_STYLE}</style>
</head>
<body>
<div class="report">
  <h1>AI Visibility Audit &mdash; {_esc(report.site)}</h1>
  <p class="meta">Audited {_esc(report.audited_at.isoformat() if hasattr(report.audited_at, 'isoformat') else report.audited_at)} &middot; schema {_esc(report.schema_version)}</p>
  <p class="headline">{_esc(s.headline)}</p>
  {first_failure_note}
  {_funnel_html(report)}
  <div class="summary-stats">
    <div class="stat stat-critical"><span class="stat-value">{s.critical}</span><span class="stat-label">Critical</span></div>
    <div class="stat stat-high"><span class="stat-value">{s.high}</span><span class="stat-label">High</span></div>
    <div class="stat stat-medium"><span class="stat-value">{s.medium}</span><span class="stat-label">Medium</span></div>
    <div class="stat stat-low"><span class="stat-value">{s.low}</span><span class="stat-label">Low</span></div>
    <div class="stat"><span class="stat-value">{s.total_findings}</span><span class="stat-label">Total</span></div>
  </div>
  {_action_list_html(report)}
  {_findings_by_stage_html(report)}
  {_observations_html(report)}
  {_answerability_matrix_html(report)}
  {_manifest_html(report)}
</div>
</body>
</html>
"""


def render_html_report_from_json(json_path: str) -> str:
    """CLI/script convenience: load a report.json file back into an
    AuditReport and render it -- used by run_audit.py so rendering
    always goes through the same schema validation the report itself
    was written with, never a raw dict."""
    data = Path(json_path).read_text(encoding="utf-8")
    report = AuditReport.model_validate_json(data)
    return render_html_report(report)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: render_html.py <report.json> <out.html>", file=sys.stderr)
        raise SystemExit(2)
    html_out = render_html_report_from_json(sys.argv[1])
    Path(sys.argv[2]).write_text(html_out, encoding="utf-8")
    print(f"Wrote {sys.argv[2]}")
