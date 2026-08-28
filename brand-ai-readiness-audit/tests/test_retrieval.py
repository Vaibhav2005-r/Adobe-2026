"""Unit tests for brand_audit.retrieval (BM25Retriever)."""

from __future__ import annotations

from brand_audit.chunk import Chunk
from brand_audit.retrieval import BM25Retriever, tokenize


def _chunk(text: str, url: str = "https://example.com/", idx: int = 0) -> Chunk:
    return Chunk(text=text, url=url, chunk_index=idx, token_count=len(text.split()), section_heading=None, char_offset=0)


def test_tokenize_lowercases_and_drops_stopwords():
    assert tokenize("The Quick Brown Fox") == ["quick", "brown", "fox"]


def test_exact_term_match_scores_higher_than_partial():
    chunks = [
        _chunk("the price is one hundred dollars for the widget", idx=0),
        _chunk("we sell many different widgets and gadgets here", idx=1),
    ]
    r = BM25Retriever()
    r.index(chunks)
    results = r.query("price of the widget", top_k=2)
    assert results[0].chunk.chunk_index == 0


def test_no_matching_terms_returns_empty():
    r = BM25Retriever()
    r.index([_chunk("completely unrelated content about gardening")])
    assert r.query("quarterly financial earnings report") == []


def test_empty_query_returns_empty():
    r = BM25Retriever()
    r.index([_chunk("some content")])
    assert r.query("", top_k=5) == []


def test_empty_index_returns_empty():
    r = BM25Retriever()
    r.index([])
    assert r.query("anything", top_k=5) == []


def test_scoring_is_deterministic_across_repeated_queries():
    chunks = [_chunk(f"content about topic {i} with widget pricing details", idx=i) for i in range(20)]
    r = BM25Retriever()
    r.index(chunks)
    a = r.query("widget pricing", top_k=5)
    b = r.query("widget pricing", top_k=5)
    assert [(sc.chunk.chunk_index, sc.score) for sc in a] == [(sc.chunk.chunk_index, sc.score) for sc in b]


def test_tie_breaking_is_by_url_then_chunk_index_not_insertion_order():
    # Two chunks with identical text (and therefore identical BM25
    # score) indexed in reverse of their "natural" (url, chunk_index)
    # order -- the tie-break must still resolve to (url, chunk_index)
    # ascending, not whatever order they happened to be indexed in.
    chunks = [
        _chunk("widget pricing details here", url="https://example.com/b", idx=0),
        _chunk("widget pricing details here", url="https://example.com/a", idx=0),
    ]
    r = BM25Retriever()
    r.index(chunks)
    results = r.query("widget pricing", top_k=2)
    assert results[0].chunk.url == "https://example.com/a"
    assert results[1].chunk.url == "https://example.com/b"


def test_term_coverage_reflects_fraction_of_query_terms_matched():
    r = BM25Retriever()
    r.index([_chunk("widget pricing details")])
    results = r.query("widget pricing nonexistentterm", top_k=1)
    assert len(results) == 1
    assert results[0].term_coverage == 2 / 3


def test_idf_never_negative_even_for_universal_term():
    # A term appearing in every document (df == N) can make the classic
    # Robertson-Sparck Jones IDF go negative; the +1 inside the log
    # guards against that.
    r = BM25Retriever()
    r.index([_chunk("common word here"), _chunk("common word there"), _chunk("common word everywhere")])
    assert r._idf("common") >= 0
