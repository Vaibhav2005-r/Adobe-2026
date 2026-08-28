"""JSON-LD extraction, shared between extractability-audit (schema-vs-
text contradiction, required-property checks) and retrieval-simulation
(entity detection). Promoted here rather than cross-imported between
skill scripts, or duplicated -- both stages need exactly the same "walk
every JSON-LD block, including nested ones" primitive.
"""

from __future__ import annotations

from typing import Iterator

import extruct


def extract_json_ld(html: str) -> list[dict]:
    data = extruct.extract(html, syntaxes=["json-ld"])
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
