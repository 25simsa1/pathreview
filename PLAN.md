# Solution plan

**Issue:** [#24 — Hybrid retriever over-weights keyword results when query contains technology names](https://github.com/ascherj/pathreview/issues/24)

### Understand

**Root cause.** In `HybridRetriever.retrieve()` (`rag/retriever/hybrid.py`) the vector
score list and the BM25 score list are each normalized *by their own maximum*
(`vector_scores_max`, `keyword_scores_max`), blended with fixed weights
(`0.7` vector / `0.3` keyword), and filtered by `min_score` (default `0.3`). Two
coupled defects fall out of this:

1. **Per-list max-normalization discards absolute magnitude.** Dividing each list by
   its own max forces the single best BM25 hit to `1.0` no matter how weakly it
   matches. On a tech-name query ("React", "Python") a chunk from an unrelated
   document that merely repeats the term becomes the top BM25 hit and gets a
   normalized keyword score of `1.0`.
2. **`min_score` equals `keyword_weight`.** A keyword-only chunk (zero vector
   similarity) then scores exactly `0.7*0 + 0.3*1.0 = 0.30`, which clears the default
   `min_score` of `0.30`, so a semantically irrelevant wrong-document chunk is
   returned as a result.

**Expected vs. actual.** Expected: a wrong-document chunk with no semantic relevance
should not appear above genuinely relevant chunks (ideally not appear at all).
Actual (observed in the reproduction, commit `ec47932`):

```
id=rel    source=resume_1              blended=0.737 vec=1.000 kw=0.125
id=noise  source=readme_other_project  blended=0.300 vec=0.000 kw=1.000   <- returned
```

Raising the noise chunk's BM25 from `8.0` to `800.0` leaves its blended score at
`0.300` — proof the max-normalization throws away magnitude.

**Note on the issue text.** The issue says the weights are "50/50", but the code
default is `0.7/0.3`. The real mechanism is the normalization + threshold, not the
weight ratio, so the fix must change how scores are fused, not just a constant.

### Map

Files I expect to touch:

- **`rag/retriever/hybrid.py`** — primary. The normalize → blend → `min_score` filter
  logic in `retrieve()`. Also a small dead-code cleanup: `_get_all_chunks()` is called
  but its result is never used.
- **`tests/unit/test_hybrid_retriever.py`** — flip the `xfail(strict)` reproduction to
  a passing test and add the new cases below.
- **`docs/ARCHITECTURE.md`** (and/or a `hybrid.py` module docstring) — the issue carries
  a `docs` label; document the fusion/scoring formula (overlaps with issue #36, which
  notes the architecture doc doesn't explain hybrid scoring).

Read-only context I need to keep consistent with:

- `rag/retriever/keyword_search.py` — BM25 scores are unbounded and corpus-relative.
- `rag/retriever/vector_store.py` — vector "score" is a cosine/eucl similarity mapped to
  `1/(1+distance)`, already in `(0, 1]`.
- `rag/generator/review_generator.py` — consumes `retrieved_chunks` (dicts) and may read
  the numeric `score`; check before changing the score scale.

### Plan

1. **Replace per-list max-normalization with a scale-robust fusion.** Prototype two
   options and pick with the reproduction test: (a) Reciprocal Rank Fusion (rank-based,
   immune to incomparable score scales), or (b) min–max normalization using both min and
   max per list plus a gate so a keyword-only chunk cannot reach the threshold on lexical
   signal alone. Leaning RRF.
2. **Decouple the relevance threshold from `keyword_weight`.** Ensure a keyword-only
   chunk can no longer clear `min_score` automatically; apply the threshold to a
   properly-scaled fused score and document its meaning.
3. **Remove the dead `_get_all_chunks()` call** (or wire it if it was meant to feed
   keyword indexing) after confirming where BM25 indexing is supposed to happen.
4. **Update tests:** flip the reproduction to assert the wrong-document chunk is excluded;
   add cases for (a) a relevant chunk present in both lists ranking first, (b) a legitimate
   tech-name query where the term *is* central to the relevant doc (guard against
   over-correction), (c) empty lists and all-below-threshold.
5. **Document the scoring formula** in `hybrid.py` and a short `docs/ARCHITECTURE.md`
   section.

### Inputs & outputs

- **Inputs:** `query: str`, `query_embedding: list[float]`, `profile_id: str`,
  `max_chunks: int`, `min_score: float`; internally `vector_results` (`score` in `(0,1]`)
  and `keyword_results` (`bm25_score` unbounded `>= 0`).
- **Outputs:** a list of chunk dicts with a fused `score`, sorted descending, length
  `<= max_chunks`, containing only chunks that meet the relevance threshold.
- **Behavior change:** wrong-document, keyword-only chunks no longer surface above
  relevant chunks; ranking reflects combined semantic + lexical relevance on a comparable
  scale. Existing keys on each result dict (`id`, `text`, `metadata`, `score`,
  `vector_score`, `keyword_score`) are preserved.

### Risks & unknowns

- **`retrieve()` has no call sites in app code.** Repo-wide, `HybridRetriever.retrieve()`
  and `keyword_searcher.index()` are only referenced by tests — the component is not wired
  into the live request path in this seeded repo (`rag/generator/review_generator.py`
  takes `retrieved_chunks` from an as-yet-unidentified source). Unknown: is wiring in scope
  for #24, or is the retriever invoked through a path I haven't found? Resolve before
  changing the public `score`/`min_score` contract. This is also why the reproduction is a
  unit test rather than an end-to-end app trigger.
- **Changing the score scale (e.g., RRF) breaks any consumer that assumes a 0–1 blend.**
  Must grep consumers of the `score` field and `min_score` in
  `rag/generator/review_generator.py` and `rag/evaluator/` before switching fusion methods.
- **Mock embeddings are hash-random**, so integration tests against seeded profiles can't
  meaningfully assert semantic ordering; verification stays at the unit level with
  controlled vector/keyword scores.
- **Weight discrepancy** (issue "50/50" vs code "70/30"): confirmed no caller overrides the
  defaults, so the fix targets normalization, not the ratio — but I'll re-confirm during
  implementation.

### Edge cases

- Empty `vector_results` and/or empty `keyword_results` (the `default=1.0` guards divide
  by zero today; keep that behavior).
- All candidates below `min_score` → return an empty list.
- A chunk present in only one list (vector-only or keyword-only).
- A tech-name query where the term is genuinely central to the relevant document — the fix
  must not suppress legitimate keyword signal.
- A single very large BM25 outlier (the `800.0` case) must not dominate the ranking.
- Tie in fused score → stable, deterministic ordering.
