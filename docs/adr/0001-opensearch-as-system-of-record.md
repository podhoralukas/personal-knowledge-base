---
status: accepted
date: 2026-09-18
---
# OpenSearch is the only database, with `items` as current view and `versions` as append-only history

We need hybrid (BM25 + kNN) search over a personal knowledge base with full time history of every capture and a small owner-controlled taxonomy. We chose OpenSearch as the single system of record rather than adding Postgres (pgvector) or a dedicated vector/search engine, because its hybrid search pipeline is the deciding feature and one store is what a self-hosting developer can reasonably run.

History is modelled as two indices, not with OpenSearch's `_version` (which is optimistic-concurrency control, not history): `versions` is append-only (`_id = item_id:captured_at`, never updated) and `items` is the current view (`_id = item_id`, upserted on every capture with the newest version's summary/tags/embedding). There is no `is_current` flag to flip, so a capture is two idempotent writes and search over current knowledge is a plain query on `items`. The taxonomy is a third small index; it does not live in a git-tracked file because adding a tag must be a single app action.

**Considered:** Postgres + pgvector + tsvector (relational fit, but DIY hybrid ranking and faceting); Elasticsearch (identical, license); Meilisearch/Typesense (not a system of record); Qdrant/Weaviate (weak keyword search).
**Consequences:** the embedding is stored twice per Item (~6 KB); relationships (tag tree, item↔versions) are by id in the app, not foreign keys; a later Cloudflare deployment needs a managed OpenSearch reachable over HTTPS, so all OpenSearch-specific code stays behind one storage seam.

**Amendment (2026-10-16):** hosting stays local for now: an always-on Docker Compose stack (OpenSearch + the app, started with Docker Desktop) on the Owner's PC. The problem to solve was capture friction (every capture needed the stack started by hand), not reach from other devices, and a managed OpenSearch costs about $19/mo or pauses when idle on free tiers. If the KB later moves off the PC, the cheapest path found is a VPS running the same compose behind a Cloudflare Tunnel, which needs no managed OpenSearch. A Cloudflare-native store (D1 + Vectorize) would supersede this ADR.
