"""What language is this corpus in, and do our lexicons cover it?

Several checks in this pipeline are English-language instruments, not
language-neutral ones: the 18-query buyer-intent bank
(`retrieval-simulation/assets/query-templates.json`), the BM25 stopword
list, and the call-to-action phrase list in `ENGAGE-005`. Pointed at a
site in another language they don't measure worse -- they measure
nothing, while still producing confident-looking output.

Measured, not assumed. A deliberately well-built German fixture
(`tests/fixtures/non-english`, which names its brand up top on every
page, ships JSON-LD, states prices in both schema and prose, and carries
three German CTAs) audited as:

    15 of 18 buyer-intent queries unanswerable
    headline: "15 of 18 buyer-intent queries are unanswerable ..."
    CHUNK-001  medium   (false)
    ENGAGE-005 medium   "no recognizable next step" (false)
    + 5 "no page answers X-intent questions" proactive recommendations (false)

The pricing page says "Der Bergquell A1 Aktivkohlefilter kostet 149,00
EUR" -- a verbatim, attributable answer to a pricing query. Only the
three identity queries passed, and only because a brand name is the one
token that survives translation. Every one of those findings is an
artifact of asking English questions of a German site.

So this module exists to let the pipeline say "not measured" instead of
"measured, failed" -- the same contract stage (2) already honours when
Playwright is missing: skip the stage, suppress its findings, record the
degradation, never guess.
"""

from __future__ import annotations

import re
from collections import Counter

# Languages the bundled query bank, stopword list and CTA lexicon
# actually cover. Adding one means adding all three, plus a fixture --
# not just appending a code here.
LEXICON_LANGUAGES = frozenset({"en"})

# Whitespace before `lang` is required, not `\b`: `\b` sits happily
# between the hyphen and the `l` of `data-lang`, an attribute i18n
# frameworks set freely and which routinely disagrees with the document's
# real language. `xml:lang` is accepted as the equivalent it is.
_HTML_LANG_RE = re.compile(
    rb"""<html[^>]*\s(?:xml:)?lang\s*=\s*["']?([A-Za-z]{2,3}(?:[-_][A-Za-z0-9]+)*)""", re.IGNORECASE
)


def page_language(html: str | bytes) -> str | None:
    """The primary language subtag of `<html lang=...>`, lowercased
    ("de-AT" -> "de"), or None when the page doesn't declare one.

    Regex rather than a parse: this runs over every sampled page and only
    needs one attribute on one element, which is always in the first few
    hundred bytes.
    """
    raw = html.encode("utf-8", "ignore") if isinstance(html, str) else html
    match = _HTML_LANG_RE.search(raw[:4096])
    if match is None:
        return None
    return match.group(1).decode("ascii", "ignore").replace("_", "-").split("-")[0].lower()


def detect_corpus_language(pages: dict[str, str]) -> str | None:
    """Majority-declared language across the corpus, or None if no page
    declares one.

    Majority rather than "the homepage's", because a site can carry one
    stray mislabelled page, and ties break alphabetically so the result
    stays deterministic -- same site in, same report out.
    """
    declared = Counter(lang for html in pages.values() if (lang := page_language(html)))
    if not declared:
        return None
    top = max(declared.values())
    return sorted(lang for lang, n in declared.items() if n == top)[0]


def lexicons_cover(language: str | None) -> bool:
    """Whether the English-only lexicons can be trusted on this corpus.

    An *undeclared* language counts as covered. That asymmetry is
    deliberate and matches how `_readiness_for_stage` treats a missing
    `pages_examined`: act on an explicit declaration, never on an
    absence. Treating "no lang attribute" as unsupported would skip the
    crown-jewel stage on the very large number of perfectly ordinary
    English sites that simply never set the attribute -- trading a real
    false-positive class for a much larger false-negative one.
    """
    return language is None or language in LEXICON_LANGUAGES
