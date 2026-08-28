"""Chunking: turns a page's main-content HTML into overlapping,
provenance-tracked chunks for stage (4) retrieval-simulation.

Chunk boundaries are word-based, not exact-tiktoken-boundary-based --
a deliberate simplification consistent with the project's existing
"regex over model weights" posture (see brand_audit.facts). The
`token_count` field on each Chunk still reports a real tiktoken count
when available, falling back to the word count otherwise, so the
metadata is honest even where the windowing itself is an approximation.
"400-600 tokens" is a target, not a boundary the pipeline enforces
exactly -- true of most production chunkers too.
"""

from __future__ import annotations

from dataclasses import dataclass

from selectolax.parser import HTMLParser

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def _get_tiktoken_encoding():
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except ImportError:
        return None


_ENCODING = _get_tiktoken_encoding()


def count_tokens(text: str) -> int:
    """Real token count when tiktoken is installed, else a whitespace
    word-count approximation -- see pyproject.toml's `tokenize` extra."""
    if _ENCODING is not None:
        return len(_ENCODING.encode(text))
    return len(text.split())


@dataclass
class Chunk:
    text: str
    url: str
    chunk_index: int
    token_count: int
    section_heading: str | None  # nearest preceding heading -- DOM-position provenance
    char_offset: int  # offset into the page's concatenated main-content text


_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "dd", "blockquote"}


def _extract_segments(main_html: str) -> list[tuple[str, str | None]]:
    """Block-level text segments in true document order, each tagged
    with the nearest preceding heading.

    Deliberately NOT `tree.css("h1, h2, ..., p, ...")`: a grouped CSS
    selector in selectolax returns all matches of the first selector in
    the group, then all matches of the second, and so on -- concatenated
    per-selector, not merged into document order. Confirmed directly
    (see docs/progress.md): `tree.css("h1, h2, h3, p")` on
    `<h2>B</h2><h1>A</h1><p>x</p><h3>C</h3>` returns `h1 A, h2 B, h3 C,
    p x` -- reordered by tag, not the true `h2 B, h1 A, p x, h3 C`. For
    a per-segment heading-attribution walk like this one, that's a
    correctness bug, not a cosmetic one: every segment would end up
    tagged with the *last* heading in the whole document. `tree.iter()`
    walks in true document order.
    """
    tree = HTMLParser(main_html)
    segments: list[tuple[str, str | None]] = []
    current_heading: str | None = None
    for node in tree.body.iter() if tree.body else []:
        if node.tag not in _BLOCK_TAGS:
            continue
        text = (node.text() or "").strip()
        if not text:
            continue
        if node.tag in _HEADING_TAGS:
            current_heading = text
            continue
        segments.append((text, current_heading))
    return segments


def chunk_page(
    main_html: str,
    url: str,
    *,
    target_tokens: int = 500,
    overlap_tokens: int = 75,
) -> list[Chunk]:
    """Chunk a page's main-content HTML (trafilatura's HTML output, same
    as extract_detect._main_content_html) into overlapping chunks,
    provenance-tracked back to the URL, a running char offset, and the
    nearest preceding heading -- which is also prepended to the chunk's
    own text, not just tracked as metadata. Without that, a query like
    "how do I contact them" can never match a chunk whose only signal
    for "this is the contact section" is a heading that never made it
    into any chunk's actual indexed content -- a real reader sees and
    relies on section headings; a retriever that never indexes them
    doesn't."""
    segments = _extract_segments(main_html)
    if not segments:
        return []

    words: list[tuple[str, str | None, int]] = []  # (word, heading, segment_start_offset)
    running_offset = 0
    for text, heading in segments:
        for w in text.split():
            words.append((w, heading, running_offset))
        running_offset += len(text) + 1  # +1 for the joining space/newline

    step = max(1, target_tokens - overlap_tokens)
    chunks: list[Chunk] = []
    i = 0
    idx = 0
    n = len(words)
    while i < n:
        window = words[i : i + target_tokens]
        if not window:
            break
        primary_heading = window[0][1]  # provenance metadata: the section the chunk *starts* in
        # A chunk can span more than one section once target_tokens is
        # large enough for several short sections to land in the same
        # window (the realistic case, not just a small-chunk-size test
        # artifact -- confirmed by chunking this module's own docstring
        # fixture at the real default 500-token size, where an entire
        # small page landed in one chunk). Prepending only the first
        # heading would silently drop every later section's heading text
        # from the indexed content -- and a heading label is sometimes
        # the *only* place a concept is named at all (a "Warranty"
        # section whose body just says "covered for two years" without
        # ever using the word "warranty").
        seen_headings: list[str] = []
        for _, h, _ in window:
            if h and h not in seen_headings:
                seen_headings.append(h)
        body_text = " ".join(w for w, _, _ in window)
        chunk_text = f"{' / '.join(seen_headings)}\n\n{body_text}" if seen_headings else body_text
        chunks.append(
            Chunk(
                text=chunk_text,
                url=url,
                chunk_index=idx,
                token_count=count_tokens(chunk_text),
                section_heading=primary_heading,
                char_offset=window[0][2],
            )
        )
        idx += 1
        if i + target_tokens >= n:
            break  # last window already reached the end -- don't emit a near-duplicate tail chunk
        i += step
    return chunks
