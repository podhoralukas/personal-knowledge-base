# Knowledge Base v2 — Plan

Status: **phases 1–2 implemented (2026-09-21, 2026-10-02); phase 3 in progress** (design agreed 2026-09-18, 25 decisions).
This file is the running log: research findings, decisions taken so far, and the open design tree.
The glossary lives in `CONTEXT.md` (created once the first term is settled); irreversible decisions get an ADR in `docs/adr/`.

## 1. Where we are today (v1)

- RSS/page crawl (crawl4ai + feedparser) → LLM summary → `info|tech` classifier → OpenSearch (`article_summary` index, hybrid BM25 + kNN).
- LangChain agent driven from a Chainlit chat UI; `crawl_source` / `save_article` / `search_articles` / `recent_news` tools.
- Schema is flat and single-version: `url, title, summary, category, source, published_date, crawled_at, tags(unused), embedding`.
- No versioning, no real tagging, no capture path other than "ask the agent to crawl a feed".

## 2. Research: state of the art (Sept 2026)

### 2.1 Hosted "AI read-it-later / second brain" products
| Product | What it does | Gap vs. our goals |
|---|---|---|
| Readwise Reader | Best-in-class capture (extension, email, share sheet, YouTube, PDFs); AI summaries & "ghostreader" | Highlights live in Reader; not a queryable KB; no versioning; no schema control |
| Recall (recall.it) | Save → summarize → chat over articles/videos/PDFs; auto-connects notes | Closed schema, hosted only, no determinism/versioning |
| Mymind / Fabric | Visual "AI-organized" saving, no manual tagging | Opaque organisation; the opposite of deterministic |
| Raindrop.io | Collections + tags + full-text search | No AI, no versioning |

### 2.2 Self-hosted open source
| Project | Notes |
|---|---|
| **Karakeep** (ex-Hoarder, AGPL) | Closest existing thing: links/notes/images, LLM auto-tagging + summary (OpenAI or Ollama), Meilisearch full-text, Monolith full-page archive, browser extensions + mobile, REST API. Next.js + Drizzle + tRPC + Puppeteer. **Free-form tags, no history/versioning, no controlled vocabulary.** |
| Linkwarden | Archiving (screenshot/PDF/reader view), tags, collections, collaboration. No AI tagging. |
| Linkding | Minimal, fast, tags + full-text. No AI. |
| Obsidian Web Clipper + local agent | The "markdown files + local Claude Code" pattern the user explicitly does *not* want: no schema, no versioning, sorting is ad hoc. |

Takeaway: nobody in this space does **(a)** a controlled, deterministic tagging vocabulary or **(b)** time-versioned derived data. That is our edge; everything else (capture, archive, search) is commodity and we can copy proven patterns (Karakeep is the reference implementation).

### 2.3 Deterministic tagging — what the literature says
- Free-form LLM tags drift: one experiment produced 765 one-off tags without a taxonomy vs. 240 reusable tags with one.
- Proven pipeline (digital-library subject indexing, LLM4Tag/KDD 2025): LLM proposes candidates → **map to a controlled vocabulary by embedding nearest-neighbour** → confidence calibration → reject/propose-new below threshold.
- Practical recipe: a versioned taxonomy file; the LLM only *chooses* from it (structured output / enum); unknown concepts go to a "proposed tags" queue for human approval, so the vocabulary grows deliberately.

### 2.4 Versioning patterns
- Two orthogonal time axes (bitemporal): *when the source changed* vs. *when we (re)processed it*. Practical simplification: an immutable **snapshot** of the fetched source per capture, and immutable **enrichment runs** (summary/tags/embedding + model + prompt version) pointing at a snapshot. "Current" is a pointer, never an overwrite.
- Event-sourced full history is overkill for a single-user KB; append-only tables + a `current_*` view gives the same auditability with far less machinery.

### 2.5 Pi harness on Cloudflare
- Confirmed viable and actively developed: Cloudflare officially hosts pi-based harnesses (Flue, Project Think) on the Agents SDK; each agent = Durable Object with SQLite, alarms (cron), `runFiber()` durable execution, Workflows for multi-step jobs, bindings to Browser Rendering, Workers AI, AI Gateway, Vectorize, D1, R2, Queues.
- Community ports: `pi-agent-cf` (pi-agent-core + pi-ai in a DO; REST + WebSocket triggers; early-stage, 3 commits), `pi-worker` (forks of pi-coding-agent for Workers; SQLite-backed FS; DO-alarm cron; "actively experimental"), camelAI's write-up (pi lower layers in a DO, FS in SQLite/R2, Code Mode instead of bash).
- Honest assessment: for a *fixed* pipeline (fetch → extract → summarize → tag → store) an agentic harness is more than needed; a Workflow/Queue consumer is simpler and deterministic. Pi earns its place for the *open-ended* jobs: "re-organise this cluster", "find contradictions", "answer a question across the KB", ad-hoc re-tagging campaigns.

Sources: Knolo top extensions 2026, BeeMind read-it-later comparison, burn451 AI bookmark tools, contextbolt self-hosted comparison, karakeep-app/karakeep, LLM4Tag (arXiv 2502.13481), Andy Fitzgerald "AI supported auto-categorization", event-driven.io versioning patterns, Cloudflare blog "agents-platform-flue-sdk", funtuan/pi-agent-cf, qaml-ai/pi-worker.

## 3. Decision log

(Filled in as the grilling proceeds. Newest at the bottom.)

### Round 1 (2026-09-18)

- **D1 — Versioning = Capture timestamp.** A Version is created per Capture and identified by (Item, UTC capture timestamp). This covers both "the page changed" and "we re-processed it"; the two are not distinguished by separate axes. Owner annotations are not versioned.
- **D2 — Tags are hierarchical and the Taxonomy is append-only.** Tags already assigned are never changed; the Taxonomy grows over time by adding sub-tags. The actual tag schema is designed later and expected to evolve. Open: who is allowed to add tags, and whether tags are faceted.
- **D3 — Single Owner per deployment, self-hostable.** Built for the author first; later shared with other developers who run their own instance (no multi-tenancy required, but nothing may assume localhost-only either).
- **D5 — Version creation rule.** Every Capture creates a Version with a fresh UTC timestamp, unconditionally. Content hash is stored; if the hash **and** the pipeline inputs (model, prompt version, taxonomy version) are unchanged from the previous Version, the previous Enrichment is reused instead of recomputed.
- **D6 — Captures are manual events only.** Triggered by the browser extension or the app's own UI. Any automation is a later concern and will be an agent that "presses the button" through the same ingress (HTTP or MCP) — no scheduled re-capture inside the system.
- **D7 — Taxonomy is under manual control.** Only the Owner adds Tags; the pipeline can only choose from the current Taxonomy. No LLM proposals, no autonomous growth. The `info|tech` category will be replaced; its successor is designed in a later step.
- **D8 — OpenSearch stays as the engine** (hybrid search pipelines are the deciding feature). A thin storage seam is kept in front of it so the pipeline never speaks OpenSearch directly. Alternatives considered: Postgres+pgvector (DIY hybrid), Elasticsearch (license), Meilisearch/Typesense (not a system of record), Qdrant/Weaviate (weak keyword/faceting). Taxonomy does **not** live in OpenSearch.
- **D9 — Taxonomy lives in a database table, edited through an app endpoint**, not in a git-tracked file (a commit per new tag is too much friction). Every mutation bumps a taxonomy version; each Enrichment records the taxonomy version it was produced with. Which database holds it is decided in round 4. No "match level" / confidence signal on tag assignments — explicitly rejected as unnecessary complication.
- **D10 — Capture content comes from the browser when available; the server fetches only as fallback.** The extension reads the rendered, logged-in DOM (Readability-cleaned HTML) and sends `{url, content, captured_at, channel}`; captures without content (RSS run, pasted URL, future agent) are fetched server-side with crawl4ai. One ingress endpoint for all channels. Server-side headless browsing is out of scope for v2.
- **D11 — Web articles only in v2.** `media_type` is stored on the Item and Version content is stored generically so PDFs etc. can be added as extractors later.
- **D12 — Taxonomy is a small `taxonomy` index in OpenSearch** (one doc per Tag + one counter doc for the taxonomy version). Loaded whole into memory by the pipeline.
- **D13 — Tags are optional.** Zero tags is a valid Enrichment outcome; "untagged Items" is a plain list in the UI and serves as the signal that the Taxonomy needs a new branch. No forced closest-ancestor tag.
- **D14 — Item identity = `sha256(normalised URL)`.** Normalisation: follow redirects, lowercase scheme/host, strip tracking params (`utm_*`, `fbclid`, …), drop fragment, drop trailing slash. Original and normalised URL are both stored. Same content on another domain is a different Item; manual merge/alias is a possible later feature.
- **D15 — Two indices, no `is_current` flag.** `versions` is append-only (`_id = item_id:captured_at`), `items` is the current view (`_id = item_id`, upserted on every Capture with the latest summary/tags/embedding + `captured_at` of the newest Version + annotations). OpenSearch's native `_version` is concurrency control, not history, and is not used for Versions. (Pending Owner confirmation, round 5.)
- **D15 confirmed.** Two indices `items` (current view) + `versions` (append-only). HTML is not stored. What a Version stores as content is settled in round 6.
- **D16 — Fixed pipeline, no agent in the capture path.** Enrichment = deterministic Python steps with a single structured-output LLM call over HTTP (summary + tags in one call). LangChain and the "agent instructs the crawl" pattern are dropped; crawling is plain code. Pi/agents are not part of v2 at all.
- **D17 — Async ingress with FastAPI background jobs.** `POST /capture` persists the Version content and returns 202 immediately; enrichment runs in a background task. (Owner has a prior FastAPI project with this pattern to reuse as reference.) Because content is persisted before enrichment, a lost job is simply re-runnable.
- **D18 — Chainlit is dropped.** Query surface = (ii) a static web UI served by FastAPI (search, Item + Version history, Taxonomy editing, untagged list) and (iii) an MCP server over the same operations, added after the UI. Any future "do more than capture" automation is an MCP client, not a bespoke Pi harness.
- **D19 — A Version stores the summary + key information, not the full article text.** Full text was judged overkill. Consequence, accepted: the Enrichment is split into two steps with different inputs — **summarise** (input: fetched text; runs once per Capture, needs a fetch) and **tag** (input: the stored summary; re-runnable at any time against a newer taxonomy version without re-fetching). Re-summarising an old Version is therefore impossible without a new Capture; versioning may be refined once the system is in use.
- **D20 — RSS/source capture stays as an app-triggered action** ("capture newest N from source"); each entry is a normal server-fetched Capture through `POST /capture`. Sources are a small list in the app. No scheduling (D6).
- **D21 — LLM access through one thin provider adapter** (structured-output call + embeddings), provider chosen by config; OpenAI implemented first (keeps the existing embedding space). Every Enrichment records `model`, `prompt_version`, `taxonomy_version`, `embedding_model`.
- **D22 — Extension: one WebExtension (MV3) codebase for Chrome + Firefox, TypeScript, lives in this repo, loaded unpacked during development.** Auth = static API token configured in the extension options, sent as `Authorization: Bearer`; server URL configurable. No store publishing in v2.
- **D23 — Evolve the current repo in place; reuse what fits, delete the rest** (LangChain, Chainlit, the agent). v1 data is not migrated: v2 writes to new indices (`items`, `versions`, `taxonomy`) and the v1 `article_summary` index is left untouched (not deleted). Content is re-captured through the new pipeline.
- **D24 — UI = FastAPI + Jinja templates + htmx.** No Node toolchain for the app; TypeScript only in the extension.
- **D4 — Keep the local stack for now (Python + OpenSearch in Docker); Cloudflare hosting is a later stage.** OpenSearch stays because embeddings/hybrid search are a hard requirement. Flagged for discussion: OpenSearch is not a Cloudflare-native service, so "later Cloudflare" means a managed OpenSearch reachable over HTTP or a storage seam that allows swapping.

### Round 8 (2026-10-02, during phase 2)

- **D25 — Re-tagging always appends a Version.** The re-tag action tags the Item's current Version against the current Taxonomy and stores the result as a new Version (channel `retag`, timestamp = re-tag time, summary/embedding/content hash carried over, `reused_from` pointing at the Version that produced the summary), even when the tags come out unchanged. Versions stay immutable and every tagging decision is on record; accepted cost: one extra Version per Item per re-tag run. Alternatives rejected: a Version only when tags change; overwriting the Item's tags only.

### Round 9 (2026-10-05, during phase 3)

- **D26 — The Owner can delete an Item.** Deletion is hard: the Item and its whole Version history are removed (`DELETE /items/{id}` → 204, Delete button on the Item page). Use case: throwaway or useless captures. Re-capturing the URL later creates the Item afresh. An enrichment or re-tag that finishes after the delete drops its result instead of bringing the Item back. Alternative rejected: soft delete (an `archived` flag every list and search query would have to filter).

- **D27 — Re-tags only add; the Owner's tag decisions override the pipeline.** Model and example: [tagging.md](tagging.md). (1) A re-tag shows the LLM the whole Taxonomy minus the Item's rejected Tags and merges the answer into the existing pipeline tags; a suggested Tag replaces only its own ancestor (`ai` → `ai/rag`). This fixes the phase 2 re-tag, which replaced the tags and so contradicted D2. (2) The default re-tag targets untagged Items plus Items tagged with an ancestor of a Tag added since they were last tagged; "re-tag all" (every Item, confirmed) stays, also additive. D25 still holds: each re-tag appends a Version. (3) A new Capture tags its new content from scratch, never offering rejected Tags. (4) Owner tag decisions live in the Item's Annotations as owner tags and rejected tags; the Item's tags = pipeline ∪ owner − rejected. Untag, add-by-hand and "allow again" are per Item on the Item page and create no Version. (5) The extension may send Tags picked from the existing Taxonomy with a Capture; they become owner tags and the LLM tag step is skipped for that Capture. New Tags are created only in the Taxonomy editor (D7). Bulk untag is deferred. ✅ Built 2026-10-05: `POST /capture` takes `tags`; `POST /items/{id}/tags`, `DELETE /items/{id}/tags/{path}` (untag), `DELETE /items/{id}/rejected-tags/{path}` (allow again); the same three on the Item page; tag checkboxes in the extension popup.

- **D28 — The Taxonomy can be corrected, not just grown.** Refines D2/D7's "never renamed or removed". The Owner can (1) edit a Tag's description (no LLM call, no re-tag; future tag calls see the new text), (2) delete a Tag nothing uses — no Item, Version, owner/rejected tag or sub-tag carries it, (3) rename a Tag: a change of spelling or position (`ai/reserach` → `ai/research`, `ai/research` → `research`), never of meaning, rewritten everywhere the path appears — the Tag and its sub-tags, Items, Annotations and past Versions. Renaming onto an existing path is refused (merge is a separate, deferred feature); a moved Tag's new parent must exist. Rejected alternative for renames: keeping old Versions untouched and translating old paths on read. Editor UI: an interactive tree (connector lines, collapsible branches, counts) with inline htmx actions per Tag (+ sub-tag, edit description, rename, delete when unused) instead of a Mermaid diagram, which can't be edited in place and does not scale past a few dozen Tags. ✅ Built 2026-10-05: `PATCH /taxonomy/tags/{path}` (`description` and/or `path`; the rename is applied first) and `DELETE /taxonomy/tags/{path}` (409 while used or with sub-tags); in OpenSearch one painless `update_by_query` per index rewrites every tag list, and the moved Tag documents are recreated under their new ids. The tree's actions are plain HTML forms in `<details>` (no extra JS); a Tag shows *delete* only when it can be deleted.

- **D29 — Items are filtered and ordered by their saved date (first captured, UTC).** Not the newest Version's time: a re-tag appends a Version (D25), so "newest first" by that time reshuffled the whole list after a re-tag run. The published date is not used (often missing, LLM-extracted, stored only on Versions); it may become its own filter later. Filter: an optional from–to date range in UTC, both ends inclusive, `to` open-ended (up to now) when empty, plus quick links for the last 7 and 30 days. Applies to the Items list (with the tag filter), the untagged list, search (with the tag dropdown) and `GET /search?from=&to=`; the range carries over between those views like the tag filter. ✅ Built 2026-10-05: `DateRange` (whole UTC days, inclusive) on `list_items`, `list_untagged_items` and `search` in both storages (OpenSearch: a `range` filter on `first_captured_at`, also inside the k-NN filter); Item cards show "saved …"; an invalid range shows "Dates ignored: …" in the UI and is a 422 in the API.
- **D30 — The Owner can write a Note at Capture.** The extension popup has an optional note field; the note travels on the Version (the Item does not exist until the first Version is enriched, like picked Tags) and is appended below the Item's Annotation notes when that Version becomes current, so a note sent with a later Capture never overwrites an earlier one. On the Item page the note is edited as a whole (last write wins; empty clears it). The note is never sent to the LLM (Enrichment stays derived from content alone) and is matched by keyword search, not by the embedding. Popup: the Capture button keeps focus (Alt+Shift+K, Enter still captures at once); Ctrl+Enter in the note captures. ✅ Built 2026-10-05: `note` on `CaptureRequest` and `Version` (cleared on re-tag Versions), `Annotations.noting` appends with a blank line; `PUT /items/{id}/notes` and `POST /ui/items/{id}/notes` replace the whole Note; `annotations.notes` added to `SEARCH_FIELDS`; `NOTE_MAX_CHARS` limits what is sent, not the stored, appended Note.

### Round 10 (2026-10-06)

- **D31 — The Owner can write a Thought: an Item with no URL.** A Thought is an optional title plus plain text, written in the web UI or via the API (not the extension); it is the plainest Item, and an article is an Item with a source behind it (URL, summarise step, Note). Every Item has a title and a text the pipeline works on: for an article that text is the summary of the fetched content, for a Thought it is what the Owner wrote, so the pipeline is `[summarise, articles only] → tag → embed` with tag and embed reading `(title, text)` for both kinds. One `Item` class whose Kind (`article` | `thought`) lives in the existing `media_type` field, no class hierarchy: the kinds differ in only a few fields, and a discriminated union would leak into every storage read, template and search result. (1) **Kind is not a Tag** and never in the Taxonomy; it is shown as a badge and filterable like a Tag (`kind=` on `/search`, the listings and `/items/untagged`; a Kind selector beside the tag and date filters). (2) **Id**: `sha256("thought:" + written-at timestamp)`, deterministic like an article's URL hash, stable across edits; a client retrying with the same `written_at` lands on the same Thought. The title is not the identity (it is optional, editable, and not unique). (3) **Stored as written**: a Thought's Version keeps its title and full text (amends ADR-0002, which keeps only summaries for articles). The text is keyword-searchable and embedded; it is never summarised. Empty title → the first line of the text, truncated. Limit `THOUGHT_MAX_CHARS` = 20 000; the embedding and tag inputs are truncated, the stored text is not. (4) **Editing adds a Version** (writing and editing are not Captures: nothing is fetched); the saved date stays when it was first written. Edited text is tagged from scratch like a new Capture (rejected Tags never offered; owner and rejected tags carry over); an edit that changes only the title reuses the previous embedding and tags with no LLM call. (5) **Picked tags** at writing or editing follow D27(5): they become owner tags and the tag step is skipped for that Version. (6) **Visible at once**: unlike an article, a Thought's Item is stored (or updated) when written, showing the new text and keyword-searchable immediately; the tags and embedding follow when the pipeline finishes. A failed enrichment leaves the Item visible with the new text and the previous tags/embedding (or none), marked "not enriched" with a retry action. (7) **No Note** on a Thought: the Note editor is hidden and `PUT /items/{id}/notes` answers 422; the Owner edits the Thought itself. (8) Re-tags include Thoughts like any Item. API: `POST /thoughts` `{title?, text, tags?, written_at?}` → 202 `{item_id, version_id}`; `PUT /thoughts/{item_id}` `{title?, text, tags?}` adds a Version. UI: "Write a Thought" form beside the capture form, edit form on the Thought's page. ✅ Built 2026-10-06: `Kind` enum (stored as `media_type`), `ThoughtRequest`/`ThoughtEdit`, `Version.kind/title/text`, `Item.text`, `Item.rebuilt` (one view rule for both kinds), `Pipeline.write/edit/retry`; `POST /thoughts/{id}/retry` (409 unless the current Version failed) and the UI's Retry; `text` added to `SEARCH_FIELDS`; `kind=` on `/search`, `/items/untagged` and every UI list, carried between views like the dates. An edit is stamped after the Thought's newest Version, so a `written_at` in the future cannot make later edits look older.

- **D32 — The Owner can delete a single Version, of any Item.** Article, Thought and re-tag Versions alike (`DELETE /versions/{id}` → 204; a delete action on each Version on the Item page). Until now a Version disappeared only with its whole Item (D26). (1) Deleting the current Version rebuilds the Item from the newest remaining Version (the main use: undoing a bad Thought edit). (2) The Item's last Version cannot be deleted (409); delete the Item instead (D26). (3) The Annotations stay as they are: a Note or owner tags that came with the deleted Version were already moved into them, and Annotations are not versioned. (4) The saved date stays, even when the first Version is deleted. (5) A pending Version can be deleted; its enrichment result is dropped when it finishes, as for a deleted Item. ✅ Built 2026-10-06: `Storage.delete_version`, `kb/versions.py`; the UI offers *delete* on each Version while the Item has more than one. Refusal covers one more case than (2): an article's last *enriched* Version, since without it the Item would have nothing to show (its remaining Versions are pending or failed).

### Round 11 (2026-10-12)

- **D33 — MCP server: four hand-written tools for a chat on this machine.** Phase 5, moved ahead of 3E. Purpose: recall from a chat (Claude Code), plus writing a Thought; capture and the automation agent (D6/D18) come later. (1) **Transport**: streamable HTTP mounted in the FastAPI app at `/mcp`, registered in Claude Code with the `API_TOKEN` bearer as a header (no OAuth). The tools call the same `kb` functions as the routes and use the app's background enrichment. Rejected: a separate stdio process (a second program with its own URL and token; importing `kb` directly would run enrichment in the chat client's subprocess). Claude Desktop, which runs only local stdio servers, can be bridged later with `mcp-remote`. (2) **Hand-written** with the official `mcp` SDK, not generated from the OpenAPI schema, which would expose every endpoint, name tools after routes and return embeddings. Results are structured and never carry embeddings or raw content. (3) **Tools**: `search(query, tag?, kind?, saved_from?, saved_to?)`: the search page's call, same 20 results; per Item title, Kind, Tags, saved date, URL, score, UI link, Note and body (article: summary + key points; Thought: text cut at a limit in `kb/config.py`), plus the `semantic` flag. No relevance cutoff, as on the page: the agent judges from the scores. `write_thought(text, title?)` → `item_id` + UI link; no tags, so the pipeline tags it; its Version has `channel = mcp` (a Thought written through an agent is still the Owner's). `tag_item(item_id, tag)` adds an owner tag to any Item (D27(4)), described as used only when the Owner explicitly asks; add only, no untag. `list_tags()` returns every Tag path with its description, read fresh on each call. An unknown tag in `search` or `tag_item` is an error pointing to `list_tags`. (4) **Out for now**: capture, editing a Thought, Notes, untag, deletes, Taxonomy edits, re-tag. They are rare, the UI does them, and a wrong call by an agent costs data or money. Tests stay offline (in-memory storage, `FakeLLM`, the SDK's in-memory client), including a tag added while a Thought's enrichment is still running. ✅ Built 2026-10-12: `kb/mcp_server.py` (FastMCP, stateless, JSON responses) routed at `MCP_PATH` behind a bearer guard; its session manager runs in the app's lifespan; enrichment started by `write_thought` runs as a kept asyncio task. `Channel.MCP` (refused on `POST /capture`); storage search returns `Match` (an Item with its score), so `GET /search` results now also carry `score`. A long Thought's text is cut at `MCP_THOUGHT_TEXT_CHARS` in search results. The SDK's DNS-rebinding check admits only `localhost`/`127.0.0.1`/`[::1]` as Host.

## 4. Open design tree

- [x] What "versioning" means → D1
- [~] Tagging → D2, D7, D9, D12, D13; parked for a later step: facets / successor of `info|tech`
- [x] Item identity → D14
- [x] Index layout → D15
- [x] Pipeline shape → D16, D17
- [x] Query surface → D18
- [x] Version content → D19 (summary only; tag step re-runnable from summary)
- [x] RSS channel → D20
- [x] LLM provider + provenance fields → D21
- [x] Extension → D22
- [x] v1 code/data → D23
- [x] UI tech → D24

**Frontier empty as of round 7.** Parked for a later step: successor of `info|tech` (facets), Cloudflare hosting, MCP-driven automation agent.
- [x] Capture payload / ingress contract → D10
- [x] Content types → D11
- [x] Users / hosting → D3, D4, D8 (seam in front of OpenSearch)
- [x] Version creation rule + triggers → D5, D6
- [ ] Pipeline shape: fixed workflow vs. pi agent; where pi is used
- [ ] Query surface: chat, search UI, MCP server, API

## 5. The system (consolidated from D1–D24)

### 5.1 Components

```
browser extension (TS, MV3)  ──POST /capture──▶  FastAPI app (Python)  ──▶  OpenSearch (Docker)
web UI (Jinja + htmx)        ──▶  same app             │                    items / versions / taxonomy
MCP server (later)           ──▶  same operations      └─ background job: enrichment pipeline
                                                           fetch (fallback) → summarise → tag → embed → store
```

- **Ingress** — `POST /capture {url, content?, captured_at?, channel}` → normalise URL, compute item_id, persist Version stub, `202 {item_id, version_id}`, enqueue enrichment.
- **Pipeline** (fixed, deterministic order):
  1. *Fetch* — only if `content` missing (crawl4ai, reused from v1). Extension-supplied HTML is converted to markdown server-side.
  2. *Hash* — content hash; if equal to the Item's newest Version hash **and** model/prompt/taxonomy/embedding versions are unchanged → copy previous Enrichment, done.
  3. *Summarise* — one structured-output LLM call → `summary`, `key_points`, `title`, `published_date` (if found), `language`.
  4. *Tag* — second structured call, input = summary, output = subset of current Taxonomy (may be empty). Re-runnable on its own for re-tag campaigns.
  5. *Embed* — embedding of `title + summary`.
  6. *Store* — append `versions` doc, upsert `items` doc.
- **Taxonomy service** — add Tags, edit descriptions, rename, delete unused (D28), bumps `taxonomy_version`, exposes "re-tag all Items since taxonomy version N" as an action.
- **Sources** — list of feeds/pages; "capture newest N" fans out into ordinary captures.
- **UI** — search (hybrid), Item page with Version list, untagged Items, Taxonomy tree, Sources.
- **MCP server** (D33) — `search`, `write_thought`, `tag_item`, `list_tags` at `/mcp` in the same app.

### 5.2 Data model (OpenSearch)

`items` (`_id = item_id = sha256(normalised_url)`, upserted)
: `normalised_url, original_url, media_type, first_captured_at, captured_at (newest), current_version_id, title, summary, key_points, tags[], embedding, annotations{notes}`

`versions` (`_id = item_id:captured_at`, append-only)
: `item_id, captured_at, channel, content_hash, title, summary, key_points, published_date, language, tags[], embedding, model, prompt_version, taxonomy_version, embedding_model, enrichment_reused_from?`

`taxonomy` (`_id = tag path`, e.g. `ai/retrieval/rag`)
: `path, parent, name, description, created_at, created_in_taxonomy_version`; plus one doc `_meta` holding `taxonomy_version`.

### 5.3 Build phases

1. **Core + ingress** — ✅ done 2026-09-21. `kb/` package; `Storage` seam (OpenSearch + in-memory) with `items`/`versions`; `POST /capture` with server-side fetch; pipeline steps 1, 2, 3, 5, 6 (tag step stubbed to `[]`); `LLMClient` over any OpenAI-compatible endpoint. Verified by capturing a smol.ai issue end to end through the HTTP API.
   Deviations from the text above: the fetch runs *before* the 202 (so the stored stub always has content and the post-redirect URL); `Version.content` is kept while `status` is `pending`/`failed` and dropped on enrichment; the `taxonomy` index is left to phase 2.
2. **Taxonomy + tagging** — taxonomy index and endpoints; tag step; re-tag action; untagged list.
   ✅ done 2026-10-02.
   - [x] Taxonomy store: `Tag`/`Taxonomy` models, `taxonomy` index, `kb.taxonomy.add_tag`. Deviations: `parent` and `name` are derived from `path`, not stored; a Taxonomy snapshot's version is the highest `created_in_taxonomy_version` among its Tags (the `_meta` counter only allocates numbers), so a snapshot never claims a version whose Tag it doesn't contain. Tag paths are lowercase slug segments (`[a-z0-9-]`) joined by `/`.
   - [x] Endpoints: `GET /taxonomy` (tags + version), `POST /taxonomy/tags` (201; 409 existing, 422 invalid path or missing parent).
   - [x] Tag step (`kb/pipeline/tag.py`): input = title + summary + key points; the Taxonomy is listed in the prompt and paths outside it are dropped, so the model can only choose. Empty Taxonomy → no LLM call. The pipeline reads the current Taxonomy from storage per enrichment. Enrichment additionally records `tag_model` and `tag_prompt_version`; Items carry `taxonomy_version` so stale ones can be queried. Refinement of D5: same content + same summary inputs but a newer Taxonomy reuses the summary/embedding and re-runs only the tag step.
   - [x] Re-tag (D25): `POST /taxonomy/retag` → 202 `{taxonomy_version, item_count}`, re-tags Items whose `taxonomy_version` is older than the current one (`?all=true`: every Item) in a background task; per-Item failures are logged and skipped. `channel=retag` is rejected on `POST /capture`.
   - [x] Untagged list: `GET /items/untagged`, newest first, without embeddings.
   - `ensure_indices` now also puts the mapping on existing indices, so new fields are added to data from earlier phases.
3. **Web UI** — search, Item/Version pages, taxonomy editor, sources + "capture newest N".
   - [x] A. Skeleton + browsing (2026-10-02): Jinja templates in `kb/templates`, htmx 2.0.11 vendored in `kb/static` (no CDN), pages under `/ui` (`/` redirects there) so they don't collide with the JSON API. Login form takes the `API_TOKEN` and sets an HttpOnly, SameSite=Lax cookie; the JSON API stays bearer-only and ignores the cookie. Items list (newest first, `?tag=` filter including sub-tags), capture-a-URL form, Item page with Version history and htmx-loaded Version details; a pending capture polls every 2 s until enriched. `POST /capture` now rejects a malformed URL (422) before fetching.
   - [x] B. Hybrid search (2026-10-02): `ensure_indices` provisions the `kb-hybrid` search pipeline (min-max normalisation, arithmetic mean, weights 0.5/0.5 in `kb/config.py`). One hybrid query = BM25 `multi_match` over title^2/summary/key_points + k-NN (k=50) on the Item embedding, tag-subtree filter applied to both, top 20. The query is embedded once per search (one embedding call); if that fails the search falls back to keywords only and says so. `GET /search?q=&tag=` → `{items, semantic}`; UI page `/ui/search` with a tag dropdown. No relevance cutoff: k-NN always returns its k nearest, so in a small KB unrelated Items trail at the bottom with near-zero scores.
   - [x] C. Taxonomy editor (2026-10-05): `/ui/taxonomy` shows the Tag tree ordered by path segments, each Tag with its Item count (sub-tags included, one OpenSearch `filters` aggregation) linking to the Items list under it, and a "+ sub-tag" link that pre-fills the add form with `parent/`. Add-tag errors (409 existing, 422 invalid path or missing parent) re-render the form with the input kept. Re-tag panel: count of Items tagged against an older taxonomy version with a button for those, plus "re-tag all"; both confirm first (one LLM call per Item) and run in the background like `POST /taxonomy/retag`. `/ui/untagged` lists untagged Items. Tags were add-only at this point; D28 added rename and delete.
   - [ ] D. Sources + "capture newest N" — postponed until after phase 5 (2026-10-06).
   - [ ] E. Ease of use — after phase 5 (decided 2026-10-06 to come first; swapped 2026-10-12): a pass over the whole app for how easy the everyday actions are: saving (capture, writing a Thought), filtering (tag, Kind, dates, search), adding a Note or tags, editing and deleting. Scope and findings to be worked out at the start.
4. **Extension** — Readability capture, token auth, options page; load unpacked in Chrome and Firefox.
   ✅ done 2026-10-05, ahead of 3C/3D: server-side fetches hit consent walls (Seznam's CMP redirect was captured as the article) and bot checks (Cloudflare challenge on irozhlas.cz), which the Owner's own browser has already passed. `extension/`: TypeScript bundled by esbuild into `extension/dist` (loaded unpacked), tests on Node's built-in runner. The popup injects Mozilla Readability into the active tab (`activeTab` + `scripting`, no content script on every page) and posts the article HTML, with an `<h1>` title, to `POST /capture` with `channel=extension`; when `isProbablyReaderable` says no, the whole page is sent. Capturing is an explicit button press (D6); Alt+Shift+K opens the popup. Options: server URL + token in `storage.local`, saving tests the connection via `GET /taxonomy`. The API allows CORS from `chrome-extension://` and `moz-extension://` origins only, so neither browser needs a host permission for a configurable server.
5. **MCP server** — ✅ done 2026-10-12, see D33. Next: 3E, then 3D.
6. *(later, out of v2)* facets / `info|tech` successor, Cloudflare hosting, automation agent, alias/merge of Items, PDF extractor.
