---
status: accepted
date: 2026-09-18
---
# No agent framework in the capture path: fixed pipeline, plain HTTP LLM calls, MCP for automation

v1 drove crawling and saving through a LangChain agent in a Chainlit chat. For v2 the enrichment steps are known in advance (fetch → hash → summarise → tag → embed → store), so an agentic loop only adds nondeterminism, latency and cost — the opposite of the "deterministic" requirement. v2 uses a fixed Python pipeline with two structured-output LLM calls through a thin provider adapter (no LangChain), triggered asynchronously by `POST /capture` via FastAPI background jobs. Chainlit is dropped in favour of a server-rendered UI.

Open-ended automation (an agent that captures on its own, researches around an Item, proposes taxonomy branches) is deliberately *outside* the system: it is any MCP client calling the same operations the UI uses. A hosted Pi harness on Cloudflare was considered for this and rejected for v2 as premature; it remains a possible MCP client later.
