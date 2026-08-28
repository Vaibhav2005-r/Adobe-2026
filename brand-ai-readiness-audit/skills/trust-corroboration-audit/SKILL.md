---
name: trust-corroboration-audit
description: Internal pipeline stage of the Brand AI Readiness Audit, invoked by ai-visibility-orchestrator. Not meant to be invoked directly. Owns stage 5 CITE -- is it quotable and trusted -- via entity anchoring and sameAs checks, name-collision detection, freshness/staleness, attribution and statistic density, and description-drift checks across title/meta/JSON-LD/OG/footer.
metadata:
  role: stage
  stage: cite
---

# trust-corroboration-audit -- Stage ⑤ CITE

Answers: **is it quotable and trusted?** A fact can be reachable,
rendered, extractable and still lose the citation to a better-framed
third party, or fail to converge on one canonical identity at all.

## Detects

- Entity anchoring: `Organization` JSON-LD `sameAs` to authoritative
  profiles, Wikidata/Wikipedia anchors, name/address/contact consistency
  across the site's own footers.
- Name-collision detection (off-site, recommend-only, per Appendix D).
- Freshness/staleness: `dateModified` vs. content-derived dates vs.
  contradictions.
- Attribution and statistic density (per the KDD 2024 GEO study cited in
  `docs/build-plan.md` Part 2 §⑦, source citations/statistics/quotations
  measurably move visibility).
- Description drift: is the brand's one-line self-description consistent
  across `<title>`, meta description, JSON-LD, OG tags, and footer?

Field research already produced two real, evidence-gathered candidate
mechanisms for this stage -- both currently held as **observations**,
not shipped findings, per the falsification discipline (single query,
not yet reproduced): third-party pricing/comparison content displacing
brand-domain citations even when the brand's own page is technically
fine (`TRUST-001`, reproduced 3-for-3 so already promoted), and a
query-language / content-language mismatch ceding citation to
translated third-party summaries (`TRUST-003`). See
`references/taxonomy.md` at the orchestrator.

## Input / output contract

Reads the corpus survivors and, where available, the
`answerability_matrix` from `retrieval-simulation`. Writes a
`StageResult` with `stage: cite`.

## Status

Not yet implemented -- see `docs/progress.md` at the repo root.
