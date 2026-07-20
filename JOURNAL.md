# Module 3 Journal — PathReview

## Week 7 — Issue selection

**Issue link:** https://github.com/ascherj/pathreview/issues/24

**Issue title:** Hybrid retriever over-weights keyword results when query contains technology names

**Tier:** [ ] Tier 1  [x] Tier 2  [ ] Tier 3

_(Tier 2 — "Intermediate: requires cross-module understanding." The fix lives in the
RAG retriever but I need to reason about how ingestion produces chunks and how the
generator consumes retrieved results, so it isn't a one-file-in-isolation Tier 1 bug.)_

**Problem summary:**
PathReview retrieves context with a hybrid retriever (`rag/retriever/hybrid.py`) that
blends a vector-similarity score and a BM25 keyword score into a single ranking. Each
score is max-normalized to 0–1 and then combined as a weighted sum. The problem is that
when a query contains technology names like "React" or "Python", those tokens appear in
almost every chunk (both résumé chunks and README chunks), so BM25 assigns high keyword
scores broadly and keyword matches end up dominating the blend. The retriever then
returns chunks that merely mention the technology from the wrong document instead of the
chunks that are actually relevant to the query, which feeds weaker context into the
review generator. A successful fix would rebalance the scoring so a keyword hit on a
common tech term can no longer outweigh genuine semantic relevance — for example by
normalizing more sensibly, down-weighting terms that are frequent across the corpus, or
reworking how the two scores are fused — so the top-k chunks reflect the query's intent.

**Branch name:** `fix/24-hybrid-retriever-keyword-overweight`

**Setup confirmation:** [x] App runs locally at localhost:5173
_(Verified: frontend returns HTTP 200 with title "PathReview - AI Portfolio Review
Assistant"; API up at :8000 with Swagger at /docs. The `/health` endpoint reports
postgres/redis unhealthy, but that traces to seeded bugs #154 and #155, not the local
setup — migrations, DB seeding, and startup queries all ran cleanly.)_

**Cohort ledger:** [ ] Issue added to cohort ledger

---

### Selection notes — "Is this right for me?"

- **Skill fit.** I work in RAG/retrieval regularly, so a hybrid vector+keyword scoring
  bug is familiar territory rather than a stretch. That's why I went Tier 2 instead of a
  Tier 1 test/doc fix.
- **Scope.** The change is concentrated in `rag/retriever/hybrid.py` (the blend/normalize
  step), with `keyword_search.py` and `vector_store.py` as read-only context. The issue
  estimates 4–6 hours and the blast radius is small — no schema, API, or frontend changes
  — which fits comfortably inside the Week 8–9 window and leaves room to add tests.
- **Understanding / verifiability.** I already read the retriever and can point to the
  exact mechanism (max-normalize each score, weighted sum, filter by `min_score`, sort).
  I can reproduce it with a tech-name query against the seeded profiles and assert on the
  returned chunk ordering, so there's a clear before/after test.
- **Watch-outs.** The issue text says the weights are "50/50", but the code default is
  actually `vector_weight=0.7 / keyword_weight=0.3`, so part of the work is confirming
  the real over-weighting mechanism (normalization + corpus-frequent terms) rather than
  just flipping a constant. I'll confirm the reproduction before proposing a fix.
