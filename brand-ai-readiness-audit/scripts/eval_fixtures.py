#!/usr/bin/env python3
"""Day 9 evaluation harness: runs the full pipeline against every fixture
in tests/fixtures/, compares findings against a hand-authored ground
truth (the same expectations each fixture's own dedicated test file
already asserts -- not reinvented here, just tabulated across all of
them at once), and computes precision/recall/false-positive-rate.

This is maintainer/CI tooling, not a shipped skill capability -- a judge
running the marketplace never needs this script. It exists to satisfy
docs/build-plan.md Part 6/Part 7 (Day 9): "compute precision, recall and
false-positive rate on the controls. Publish the confusion matrix."

Ground truth is deliberately narrow and honest: a fixture only "counts"
toward precision for the stages it actually certifies as clean (the
same inclusion-list discipline the test suite itself uses, established
Day 6 after an exclusion-list needed editing every time a new stage
landed -- see docs/progress.md). A finding on a stage this script
hasn't certified either way isn't scored as a false positive OR a true
positive; it's simply out of scope for that fixture, which is the
correct, conservative reading -- claiming a fixture "proves" a stage is
clean when it was never built to test that stage would overstate what
was actually verified.

Usage: python scripts/eval_fixtures.py [--out docs/eval-results.md]
"""

from __future__ import annotations

import argparse
import http.server
import json
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
SCRIPT = REPO_ROOT / "skills" / "ai-visibility-orchestrator" / "scripts" / "run_audit.py"

try:
    import playwright  # noqa: F401

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


@dataclass
class FixtureExpectation:
    port: int
    certified_clean_stages: set[str] = field(default_factory=set)
    expected_taxonomy_ids: set[str] = field(default_factory=set)
    needs_render: bool = False  # skip --skip-render (and skip entirely if playwright unavailable)
    note: str = ""


# Ground truth. Each entry's "why" is the reason it belongs at that
# specific value -- required by this project's own "every rule states a
# mechanism" discipline, applied here to test expectations too.
FIXTURES: dict[str, FixtureExpectation] = {
    "clean-control": FixtureExpectation(
        port=8123,
        certified_clean_stages={"reach", "extract"} | ({"render"} if PLAYWRIGHT_AVAILABLE else set()),
        note="Built Day 2-3 with no injected defects on reach/render/extract specifically (see tests/test_smoke.py).",
    ),
    "js-only-price": FixtureExpectation(
        port=8124,
        certified_clean_stages={"reach", "extract"},
        expected_taxonomy_ids={"RENDER-001"},
        needs_render=True,
        note="Empty <div id='app'> shell -- RENDER-001 is the whole point (Day 3 DoD). Confirmed empirically clean on reach/extract (no robots block, no JSON-LD).",
    ),
    "robots-restricted": FixtureExpectation(
        port=8125,
        certified_clean_stages={"reach"},
        note="Allow: / plus one path-scoped Disallow -- a compliance fixture (Day 3 review pass), not a REACH-00x defect trigger.",
    ),
    "schema-contradiction": FixtureExpectation(
        port=8127,
        expected_taxonomy_ids={"EXTRACT-001"},
        note="JSON-LD price disagrees with visible text (Day 4 DoD).",
    ),
    "schema-clean-product": FixtureExpectation(
        port=8128,
        certified_clean_stages={"extract"},
        note="Matching price, complete properties, correct heading hierarchy (Day 4 DoD control).",
    ),
    "trust-clean": FixtureExpectation(
        port=8130,
        certified_clean_stages={"cite"},
        note="Proper sameAs, recent dateModified, consistent descriptions, an attributed statistic (Day 6 DoD control).",
    ),
    "arrival-clean": FixtureExpectation(
        port=8131,
        certified_clean_stages={"arrive"},
        note="Brand named up top on every page, a CTA on every page, an analytics snippet, no redirects/consent overlay (Day 7 DoD control).",
    ),
}

# retrieval-answerable (8129) is evaluated separately below -- its ground
# truth is per-query answerability outcome, not a finding/taxonomy_id, so
# it doesn't fit the same TP/FP/FN shape as the fixtures above.
RETRIEVAL_ANSWERABLE_PORT = 8129
RETRIEVAL_ANSWERABLE_EXPECTATIONS = {
    "identity": "answerable",
    "contact": "answerable",
    "comparison": "not_answerable",  # fixture never discusses competitors
    "trust": "not_answerable",  # fixture never discusses reviews/credentials
}


def _serve(fixture_name: str, port: int) -> http.server.ThreadingHTTPServer:
    directory = str(FIXTURES_DIR / fixture_name)
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(a[0], a[1], a[2], directory=directory)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("localhost", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _run_audit(site: str, run_dir: Path, skip_render: bool) -> dict | None:
    args = [sys.executable, str(SCRIPT), site, "--run-dir", str(run_dir)]
    if skip_render:
        args.append("--skip-render")
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"  CRASH: {site} exited {result.returncode}\n{result.stderr[-2000:]}", file=sys.stderr)
        return None
    return json.loads((run_dir / "report.json").read_text())


@dataclass
class FixtureResult:
    name: str
    crashed: bool = False
    true_positives: list[str] = field(default_factory=list)
    false_negatives: list[str] = field(default_factory=list)
    false_positives: list[tuple[str, str]] = field(default_factory=list)  # (stage, taxonomy_id)
    clean_stages_checked: int = 0
    clean_stages_dirty: int = 0


def evaluate_fixture(name: str, expectation: FixtureExpectation, tmp_root: Path) -> FixtureResult:
    result = FixtureResult(name=name)
    if expectation.needs_render and not PLAYWRIGHT_AVAILABLE:
        print(f"  {name}: skipped (needs render, playwright not installed)")
        return result

    server = _serve(name, expectation.port)
    try:
        report = _run_audit(
            f"http://localhost:{expectation.port}", tmp_root / name, skip_render=not expectation.needs_render
        )
    finally:
        server.shutdown()

    if report is None:
        result.crashed = True
        return result

    findings_by_taxonomy: dict[str, list[dict]] = {}
    for f in report["findings"]:
        findings_by_taxonomy.setdefault(f["taxonomy_id"], []).append(f)

    for expected_id in expectation.expected_taxonomy_ids:
        if expected_id in findings_by_taxonomy:
            result.true_positives.append(expected_id)
        else:
            result.false_negatives.append(expected_id)

    for stage in expectation.certified_clean_stages:
        result.clean_stages_checked += 1
        stage_findings = [f for f in report["findings"] if f["stage"] == stage]
        if stage_findings:
            result.clean_stages_dirty += 1
            for f in stage_findings:
                result.false_positives.append((stage, f["taxonomy_id"]))

    return result


def evaluate_retrieval_answerable(tmp_root: Path) -> tuple[int, int, list[str]]:
    """Returns (correct, total, mismatches) for the per-query
    answerability ground truth -- a different shape from the
    finding-level confusion matrix above, so scored separately."""
    server = _serve("retrieval-answerable", RETRIEVAL_ANSWERABLE_PORT)
    try:
        report = _run_audit(
            f"http://localhost:{RETRIEVAL_ANSWERABLE_PORT}", tmp_root / "retrieval-answerable", skip_render=True
        )
    finally:
        server.shutdown()

    if report is None:
        return 0, 0, ["CRASHED"]

    correct = 0
    total = 0
    mismatches = []
    for entry in report["answerability_matrix"]:
        expected = RETRIEVAL_ANSWERABLE_EXPECTATIONS.get(entry["intent"])
        if expected is None:
            continue  # pricing/capability intents have no hard expectation here
        total += 1
        is_answerable = entry["outcome"] == "answerable"
        matches = is_answerable if expected == "answerable" else not is_answerable
        if matches:
            correct += 1
        else:
            mismatches.append(f"[{entry['intent']}] {entry['query']!r} -> {entry['outcome']} (expected {expected})")
    return correct, total, mismatches


def render_report(results: list[FixtureResult], retrieval_eval: tuple[int, int, list[str]]) -> str:
    lines = ["# Fixture confusion matrix (Day 9)\n"]
    lines.append("| Fixture | Result | TP | FN | FP |")
    lines.append("|---|---|---|---|---|")
    total_tp = total_fn = total_fp = 0
    total_clean_checked = total_clean_dirty = 0
    for r in results:
        status = "CRASHED" if r.crashed else "ok"
        lines.append(f"| `{r.name}` | {status} | {len(r.true_positives)} | {len(r.false_negatives)} | {len(r.false_positives)} |")
        total_tp += len(r.true_positives)
        total_fn += len(r.false_negatives)
        total_fp += len(r.false_positives)
        total_clean_checked += r.clean_stages_checked
        total_clean_dirty += r.clean_stages_dirty

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else float("nan")
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else float("nan")
    fp_rate_on_controls = total_clean_dirty / total_clean_checked if total_clean_checked else float("nan")

    lines.append("")
    lines.append(f"**Precision:** {precision:.2f} ({total_tp} TP / {total_tp + total_fp} flagged)")
    lines.append(f"**Recall (on fixtures' own known-positive cases):** {recall:.2f} ({total_tp}/{total_tp + total_fn})")
    lines.append(f"**FP-rate on clean controls:** {fp_rate_on_controls:.2f} ({total_clean_dirty}/{total_clean_checked} certified-clean stage checks produced a finding)")
    lines.append("")

    for r in results:
        if r.false_positives:
            lines.append(f"**False positives in `{r.name}`:**")
            for stage, tid in r.false_positives:
                lines.append(f"- {stage}: {tid}")
    for r in results:
        if r.false_negatives:
            lines.append(f"**Missed detections in `{r.name}`:** {', '.join(r.false_negatives)}")

    correct, total, mismatches = retrieval_eval
    lines.append("")
    lines.append(f"## Answerability accuracy (`retrieval-answerable` fixture)\n")
    lines.append(f"{correct}/{total} correct ({correct/total:.0%})" if total else "no queries scored")
    for m in mismatches:
        lines.append(f"- MISMATCH: {m}")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="Write the Markdown report to this path in addition to stdout")
    args = parser.parse_args()

    import tempfile

    results = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        for name, expectation in FIXTURES.items():
            print(f"Evaluating {name}...")
            results.append(evaluate_fixture(name, expectation, tmp_root))
        print("Evaluating retrieval-answerable...")
        retrieval_eval = evaluate_retrieval_answerable(tmp_root)

    report_text = render_report(results, retrieval_eval)
    print("\n" + report_text)
    if args.out:
        Path(args.out).write_text(report_text, encoding="utf-8")
        print(f"Written to {args.out}")

    any_crash = any(r.crashed for r in results)
    return 1 if any_crash else 0


if __name__ == "__main__":
    raise SystemExit(main())
