"""Tests for rag/retriever/hybrid.py

Reproduction for issue #24: "Hybrid retriever over-weights keyword results
when query contains technology names."
https://github.com/ascherj/pathreview/issues/24

Root cause under investigation
-------------------------------
`HybridRetriever.retrieve()` normalizes the vector score list and the BM25
score list *each by its own maximum*, then blends them with fixed weights and
filters by ``min_score`` (default 0.3). Because each list is divided by its own
max, the single best BM25 hit is always rescaled to 1.0 no matter how weakly it
matches in absolute terms. On a tech-name query ("React", "Python") a chunk from
an unrelated document that merely repeats the term becomes the top BM25 hit,
gets a normalized keyword score of 1.0, and therefore a blended score of exactly
``keyword_weight`` (0.30). With the default ``min_score`` of 0.30 that clears the
threshold, so a semantically irrelevant chunk from the wrong document is returned
as a result even when it has zero vector similarity to the query.

The test below asserts the *desired* behavior and is marked ``xfail(strict=True)``
so it documents the bug without breaking the suite. When the fix lands in Week 9
it will XPASS and strict-xfail will flag it, at which point the marker is removed.
"""

from unittest.mock import Mock

import pytest

from rag.retriever.hybrid import HybridRetriever


def _fake_vector_store(vector_results: list[dict]) -> Mock:
    """A VectorStore stub whose .query() returns a fixed result list.

    get_collection().get() returns an empty corpus because retrieve() computes
    _get_all_chunks() but never uses it for scoring (dead call in the source).
    """
    store = Mock()
    store.query.return_value = vector_results
    empty_collection = Mock()
    empty_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    store.get_collection.return_value = empty_collection
    return store


def _fake_keyword_searcher(keyword_results: list[dict]) -> Mock:
    """A KeywordSearcher stub whose .search() returns a fixed result list."""
    searcher = Mock()
    searcher.search.return_value = keyword_results
    return searcher


@pytest.mark.unit
class TestHybridRetrieverKeywordOverweight:
    """Reproduction suite for issue #24."""

    def _build(self, vector_results: list[dict], keyword_results: list[dict]) -> HybridRetriever:
        return HybridRetriever(
            vector_store=_fake_vector_store(vector_results),
            keyword_searcher=_fake_keyword_searcher(keyword_results),
        )

    @pytest.mark.xfail(
        strict=True,
        reason="issue #24: keyword-only wrong-document chunk is admitted at the "
        "fixed keyword_weight (0.30) and returned as a relevant result",
    )
    def test_wrong_document_keyword_spam_not_returned(self) -> None:
        """A tech-name query must not surface a wrong-document keyword-spam chunk.

        Scenario: query "React". The relevant chunk lives in the resume and is a
        genuine semantic match (high vector similarity). A chunk from an unrelated
        README repeats "React" many times (top BM25) but is not semantically
        relevant (absent from the vector results, i.e. vector similarity ~0).

        Desired: the retriever returns only the relevant resume chunk.
        Actual (bug): the README chunk is returned too, scored at exactly 0.30.
        """
        vector_results = [
            {
                "id": "rel",
                "text": "Led a React migration that cut load time 40%.",
                "metadata": {"source_id": "resume_1"},
                "score": 0.75,
            },
        ]
        keyword_results = [
            # Wrong-document spam: highest BM25, no semantic relevance.
            {
                "id": "noise",
                "text": "React React React React React",
                "metadata": {"source_id": "readme_other_project"},
                "bm25_score": 8.0,
            },
            {
                "id": "rel",
                "text": "Led a React migration that cut load time 40%.",
                "metadata": {"source_id": "resume_1"},
                "bm25_score": 1.0,
            },
        ]

        retriever = self._build(vector_results, keyword_results)
        results = retriever.retrieve(
            query="React",
            profile_id="p1",
            query_embedding=[0.0] * 8,
            max_chunks=5,
            min_score=0.3,
        )

        returned_ids = [r["id"] for r in results]
        returned_sources = {r["metadata"].get("source_id") for r in results}

        # The wrong-document chunk should not be returned at all.
        assert "noise" not in returned_ids
        assert returned_sources == {"resume_1"}
