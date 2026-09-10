---
name: trust-corroboration-audit
description: Internal pipeline stage of the Brand AI Readiness Audit, invoked by ai-visibility-orchestrator. Not meant to be invoked directly. Owns stage 5 CITE -- is it quotable and trusted -- via on-site entity-anchoring (sameAs) checks, freshness/staleness of dateModified, description-drift checks across meta/JSON-LD/OpenGraph, and attribution/statistic-density scoring. Deliberately does not run a live name-collision web search -- see Detects below for why.
license: MIT
allowed-tools: Bash, Read
metadata:
  role: stage
  stage: cite
---

# trust-corroboration-audit -- Stage ⑤ CITE

Answers: **is it quotable and trusted?** A fact can be reachable,
rendered, extractable and still lose the citation to a better-framed
third party, or fail to converge on one canonical identity at all.

## When to use

Not directly. This skill is an internal pipeline stage of the
`brand-ai-readiness-audit` marketplace, owning stage ⑤ CITE -- *is the fact
quotable and trusted?*
`ai-visibility-orchestrator` is the marketplace's single entrypoint and
drives this stage as one step of its own procedure, handing it the corpus
that survived the stages before it. Invoking it on its own gives you one
stage's `StageResult`, not an audit report.

Read-only and recommend-only, like every skill here: it fetches and reads,
and never writes to, authenticates against, or otherwise alters the audited
site.

## Procedure

- **`TRUST-005`** Entity anchoring: a named `Organization`/`LocalBusiness`
  JSON-LD node with no (or empty) `sameAs` array linking to an
  authoritative external profile.
- **`TRUST-006`** Freshness/staleness: JSON-LD `dateModified`/
  `datePublished` more than a year old.
- **`TRUST-007`** Description drift: token-overlap comparison between
  meta description, JSON-LD `description`, and `og:description` on the
  homepage.
- **`TRUST-008`** Low attribution/statistic density: pages stating
  numeric claims with no citation language anywhere, when that's the
  majority pattern across the sampled corpus.

**Deliberately not implemented: a live name-collision web search.** The
build plan's own cut list (Part 8) names this the *first* thing to cut
if behind schedule, explicitly pairing it with "keep on-site entity
anchoring" -- exactly what `TRUST-005` is. Beyond just following that
guidance, a live search is a real tension with the project's own hard
constraints: results change over time (breaks determinism -- "same site
in, same report out") and need network access to a third-party service
a judge's bare machine can't be assumed to have (breaks portability).
Name/address/contact consistency across the site's own footers and
`<title>` in the description-drift check are also not yet implemented
-- `TRUST-007` currently checks meta/JSON-LD/OG only; see Status.

Field research already produced two real, evidence-gathered candidate
mechanisms for this stage -- both currently held as **observations**,
not shipped findings, per the falsification discipline (single query,
not yet reproduced): third-party pricing/comparison content displacing
brand-domain citations even when the brand's own page is technically
fine (`TRUST-001`, reproduced 3-for-3 so already promoted), and a
query-language / content-language mismatch ceding citation to
translated third-party summaries (`TRUST-003`). See
`references/taxonomy.md` at the orchestrator.

## Inputs

Reads the stage ① REACH survivors directly (like `extractability-audit`,
not gated through RENDER or RETRIEVE): JSON-LD and meta tags live in
`<head>` and are overwhelmingly server-rendered even on JS-heavy sites,
and this stage needs raw pages, not chunked/indexed content.

## Output

Writes a
`StageResult` with `stage: cite`.

## Status

Implemented in `scripts/trust_detect.py`. All four detectors are
unit-tested against both a defect case and a clean-control case
(`tests/test_trust.py`), plus an end-to-end fixture
(`tests/fixtures/trust-clean`) with proper `sameAs`, a recent
`dateModified`, consistent descriptions, and an attributed statistic --
every detector confirmed silent on it. `TRUST-005` and `TRUST-008`
confirmed firing on real sites (not just fixtures) during the Day 6
wild-corpus sweep. The development log records the full accounting.
