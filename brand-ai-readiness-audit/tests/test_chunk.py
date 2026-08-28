"""Unit tests for brand_audit.chunk. Two of these exist specifically
because building this module surfaced real bugs (see docs/progress.md):
selectolax's grouped CSS selector doesn't preserve true cross-tag
document order, and section headings weren't part of any chunk's
searchable text at all.
"""

from __future__ import annotations

from brand_audit.chunk import _extract_segments, chunk_page, count_tokens
from brand_audit.retrieval import BM25Retriever


def test_segments_preserve_true_document_order_not_tag_grouped_order():
    # h2 before h1 before h3 -- if selectolax's grouped selector were
    # (mis-)used here, results would come back re-ordered by tag
    # (h1, h2, h3) instead of true document order (h2, h1, h3).
    html = "<html><body><h2>First</h2><p>under first</p><h1>Second</h1><p>under second</p><h3>Third</h3><p>under third</p></body></html>"
    segments = _extract_segments(html)
    headings_in_order = [h for _, h in segments]
    assert headings_in_order == ["First", "Second", "Third"]


def test_segment_heading_attribution_is_per_segment_not_last_heading_in_document():
    html = "<html><body><h1>A</h1><p>alpha</p><h2>B</h2><p>beta</p><h2>C</h2><p>gamma</p></body></html>"
    segments = _extract_segments(html)
    assert segments == [("alpha", "A"), ("beta", "B"), ("gamma", "C")]


def test_chunk_text_includes_its_own_heading():
    html = "<html><body><h1>Warranty</h1><p>Covered for two years against defects.</p></body></html>"
    chunks = chunk_page(html, "https://example.com/", target_tokens=500, overlap_tokens=75)
    assert len(chunks) == 1
    assert "Warranty" in chunks[0].text


def test_chunk_includes_every_heading_it_spans_not_just_the_first():
    # A short "Warranty" section that a large target_tokens window
    # absorbs alongside earlier sections must not lose its heading label
    # -- it may be the only place "warranty" is ever mentioned as a word.
    html = (
        "<html><body>"
        "<h1>Rowan Cast Iron Co.</h1><p>We make skillets in Montana, seasoned three times before shipping.</p>"
        "<h2>Warranty</h2><p>Every skillet is covered for two years against manufacturing defects.</p>"
        "</body></html>"
    )
    chunks = chunk_page(html, "https://example.com/", target_tokens=500, overlap_tokens=75)
    assert len(chunks) == 1
    assert "Warranty" in chunks[0].text
    assert "Rowan Cast Iron Co." in chunks[0].text


def test_heading_only_concept_is_retrievable_end_to_end():
    # The regression this whole chain of fixes was for: a query whose
    # only lexical match in the page is a section heading, not the body
    # prose under it, must actually retrieve that chunk.
    html = (
        "<html><body>"
        "<h1>Rowan Cast Iron Co.</h1><p>We make skillets in Montana, seasoned three times before shipping.</p>"
        "<h2>Warranty</h2><p>Every skillet is covered for two years against manufacturing defects.</p>"
        "</body></html>"
    )
    chunks = chunk_page(html, "https://example.com/", target_tokens=500, overlap_tokens=75)
    retriever = BM25Retriever()
    retriever.index(chunks)
    results = retriever.query("what is the warranty policy", top_k=3)
    assert len(results) == 1


def test_no_main_content_returns_no_chunks():
    chunks = chunk_page("<html><body></body></html>", "https://example.com/")
    assert chunks == []


def test_overlap_produces_shared_words_between_consecutive_chunks():
    words = " ".join(f"word{i}" for i in range(100))
    html = f"<html><body><h1>T</h1><p>{words}</p></body></html>"
    chunks = chunk_page(html, "https://example.com/", target_tokens=30, overlap_tokens=10)
    assert len(chunks) >= 2
    first_words = set(chunks[0].text.split())
    second_words = set(chunks[1].text.split())
    assert first_words & second_words  # some overlap exists


def test_chunks_are_deterministic_across_repeated_calls():
    html = "<html><body><h1>T</h1><p>Some real sentence content repeated for the test to have enough substance.</p></body></html>"
    a = chunk_page(html, "https://example.com/")
    b = chunk_page(html, "https://example.com/")
    assert [c.text for c in a] == [c.text for c in b]


def test_count_tokens_is_positive_for_nonempty_text():
    assert count_tokens("hello world") > 0
    assert count_tokens("") == 0
