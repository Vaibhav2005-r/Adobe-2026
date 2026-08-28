# Defect Taxonomy

The rule pack. Every finding emitted by any stage skill must map to an entry here. Entries are added only after field research surfaces a real, reproducible failure — never invented from a best-practices checklist.

**Admission rule (non-negotiable):** an entry must state a *mechanism* — how the retrieval pipeline actually breaks — not just a symptom. "Missing FAQPage schema" is a symptom. "Assistants that rely on FAQPage JSON-LD to extract Q&A pairs skip freeform prose, so the answer never enters the corpus" is a mechanism. If a candidate rule only helps one site in the wild corpus, it's overfitting — cut it, don't add it.

## Entry format

```
### <ID> — <short title>
- **Stage:** reach | render | extract | chunk | trust | engage
- **Mechanism:** why this actually breaks retrieval/citation (not a symptom)
- **Detection method:** how the detector identifies it, deterministically
- **Evidence artifact:** what gets captured to prove it (URL, selector/byte-offset, extracted strings, hashes)
- **Severity default:** critical | high | medium | low (per severity-model.md — blast radius × stage × confidence)
- **Fix pattern:** the mechanism-sound remediation
- **Source:** which wild-corpus site(s) surfaced this, and the query that failed
```

## REACH-00x

_(robots/AI-UA blocks, status/soft-404, canonical integrity, WAF/interstitial, sitemap health — populate from Day 1 field research)_

## RENDER-00x

_(dual-fetch differential: JS-only facts, non-text facts in image/canvas/PDF, interaction-gated content)_

## EXTRACT-00x

_(schema↔visible-text contradiction, missing/invalid structured data, semantic HTML integrity, facts locked in images)_

## CHUNK-00x

_(orphan facts, cross-page joins, boilerplate dominance — stage ④ retrieval-simulation)_

## TRUST-00x

_(entity anchoring/sameAs gaps, name collision, freshness/staleness, single-source fragility, description drift)_

## ENGAGE-00x

_(answer proximity, orientation, context reset, entry interference, next-step availability, AI-referral blindness)_

---

**Status:** empty — populate during Day 1 field research (see `docs/progress.md`). Target ~30 entries across the six stages before freezing.
