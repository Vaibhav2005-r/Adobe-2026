"""JSON-LD extraction, shared between extractability-audit (schema-vs-
text contradiction, required-property checks) and retrieval-simulation
(entity detection). Promoted here rather than cross-imported between
skill scripts, or duplicated -- both stages need exactly the same "walk
every JSON-LD block, including nested ones" primitive.
"""

from __future__ import annotations

import json
from typing import Iterator

import extruct
from selectolax.parser import HTMLParser

_LD_SELECTOR = 'script[type="application/ld+json"]'


def _salvage_json_ld(html: str) -> list[dict]:
    """Parse each `<script type="application/ld+json">` block on its own,
    keeping the ones that are valid JSON and skipping the ones that
    aren't.

    `extruct.extract` parses every block in a single pass and lets the
    first `JSONDecodeError` propagate, so *one* malformed block discards
    the whole page's structured data -- and, since nothing upstream
    caught it, took the whole audit down with it. Per-block parsing means
    a page with three good blocks and one broken one still contributes
    three.

    Also tolerates the two legacy wrappers CMS templates still emit
    around the payload -- an XML/CDATA guard (`// <![CDATA[ ... // ]]>`,
    a holdover from XHTML) and HTML comment markers -- which are not
    valid JSON but which browsers and Google's parser both accept.
    """
    blocks: list[dict] = []
    for node in HTMLParser(html).css(_LD_SELECTOR):
        raw = (node.text() or "").strip()
        if not raw:
            continue  # an empty <script> tag is not a defect worth crashing over
        for candidate in (raw, _strip_legacy_wrappers(raw)):
            try:
                parsed = json.loads(candidate)
            except (ValueError, TypeError):
                continue
            # A block may be a single object or an array of them.
            for item in parsed if isinstance(parsed, list) else [parsed]:
                if isinstance(item, dict):
                    blocks.append(item)
            break
    return blocks


def _strip_legacy_wrappers(raw: str) -> str:
    for opener, closer in (("<![CDATA[", "]]>"), ("<!--", "-->")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start != -1 and end > start:
            raw = raw[start + len(opener) : end]
    return raw.strip().strip("/").strip()


def extract_json_ld(html: str) -> list[dict]:
    """Every JSON-LD block on the page, or as many as could be parsed.

    Malformed JSON-LD is common enough in real CMS output (an unescaped
    quote in a product description, a trailing comma, a truncated
    template, an empty tag) that it cannot be allowed to raise: this is
    called from three stages -- EXTRACT, RETRIEVE and CITE -- and an
    uncaught `JSONDecodeError` from any one sampled page ended the entire
    audit. Confirmed against `extruct` directly: an empty
    `<script type="application/ld+json"></script>` alone is enough to
    raise, and that tag ships in a lot of CMS themes.

    Degrades rather than failing: whatever parses is returned. Note the
    consequence for callers -- a page whose *only* JSON-LD block is
    malformed is indistinguishable here from a page with no JSON-LD at
    all, so `EXTRACT-002` will report it as missing structured data
    rather than broken structured data. That is the less wrong of the
    two available answers (the data is, in fact, not machine-readable),
    but a dedicated "malformed JSON-LD" taxonomy entry would say it
    better.
    """
    try:
        data = extruct.extract(html, syntaxes=["json-ld"])
    except Exception:
        return _salvage_json_ld(html)
    return [block for block in data.get("json-ld", []) if isinstance(block, dict)]


def walk(node) -> Iterator[dict]:
    """Yield every dict in a JSON-LD tree, depth-first, regardless of
    nesting -- e.g. an Offer can appear top-level or nested inside a
    Product, and an Organization can appear standalone or as a
    Product's `brand`."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)
