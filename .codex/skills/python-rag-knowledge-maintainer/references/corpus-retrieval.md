# Corpus Retrieval Reference

Use this when touching Corpus traversal used by RAG, retrieval seeds, metadata prefilter, or hydration/rerank.

## Retrieval Responsibilities

- Corpus admin CRUD/tree/backfill APIs belong to app-module maintenance.
- Corpus traversal for RAG belongs here because it decides candidate FAQ/file seeds.
- Traversal should respect role and metadata prefilters before retrieval hydration.
- Candidate contracts should remain typed: file candidates expose file IDs; `app.modules.corpus.contracts.FaqCandidate` exposes FAQ IDs and is a retrieval seed, not a synthesis/review candidate.

## Hydration And Rerank

- Hydrate FAQ docs before file candidates.
- Rerank FAQ docs separately from files with Cohere.
- If FAQ answering fully covers the question, stop before file hydration/rerank.
- Hydrate and rerank file candidates only when FAQ is insufficient.
- File and FAQ entity hydration share exact-ID Redis caches. Use `MGET`, batch-query MongoDB only for missed IDs, and reconstruct results in the original candidate order.
- `inspect_samples()`, retrieval hydration, and source construction should reuse the same entity cache contract instead of creating parallel payload formats.

## Snapshot And Eligibility Cache

- Cache the typed Corpus node payload by Corpus revision, then build the filtered snapshot in memory with the existing traversal logic.
- Cache allowed file and FAQ IDs separately by eligibility revision, access scope (`student` or `privileged`), and canonical sorted-JSON metadata hash.
- Do not cache an entire request-filtered snapshot.
- Redis failures or unavailable revisions must bypass cache and read MongoDB.

## Failure Behavior

- Unexpected traversal or hydration failures should not be silently converted into "no documents" unless the path is explicitly debug/best-effort.
- Debug preview endpoints should depend on the same core retrieval/query flow where possible.
