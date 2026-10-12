---
status: accepted
date: 2026-09-18
---
# A Version stores the summary and key points, not the full article text

Storing the full extracted text of every capture was judged overkill for a personal knowledge base. A Version therefore holds only what the pipeline derived (summary, key points, tags, embedding) plus the content hash and the provenance fields (`model`, `prompt_version`, `taxonomy_version`, `embedding_model`).

To keep the taxonomy evolvable without re-fetching, enrichment is split into two steps with different inputs: **summarise** reads the fetched text and runs once per capture; **tag** reads the stored summary and can be re-run at any time against a newer taxonomy version. The accepted cost is that an old Version cannot be re-*summarised* with a better model or prompt — that requires a new capture, which for a page behind a login may no longer yield the same content. Revisit if this bites in practice; the decision is recorded so nobody "fixes" the tag step to read full text that isn't there.

**Amendment (2026-10-06):** this holds for Items with a source behind them. A Thought's Version stores its full text exactly as the Owner wrote it, because there is no source to re-fetch: that text is the only copy. It is tagged and embedded but never summarised.
