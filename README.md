Experimental, locally self-hosted solution to store information of your interest from the internet articles you browse, with the possibility to enhance them with your custom thoughts.


The website content is captured via the browser extension (Chrome/Firefox) and Crawl4AI engine, shortened and summarized using LLM API call. Then it's saved to the OpenSearch database, vectorized and pre-selected tags are applied. The search engine uses combination of keyword and semantic search. The app also contains the MCP server with search and tagging tools, enabling connection to any chat interface you use. 

The app uses manually added system of tags, which you should manually specify before using - e.g. categories to which you would like to split the information into. The article is then automatically tagged at capture.  Each article is versioned by the date it was captured. The search engine then enables for selecting the relevant information by date. 

AI usage in this app - Each capture uses single LLM API call to summarize the information for storing, and then another one to construct the vector for semantic search. Your custom OpenAI API key has to be added to the env variables once running locally. 

### Possible next development steps:
- enhancing UI of the taxonomy and search interface so that it clearer,
- adding the possibility to modify the system prompt at the extension input,
- hosting of OpenSearch db and the app container in cloud.






# Knowledge Base

A personal, self-hosted knowledge base. Web pages you find interesting are captured (from a browser extension, the web UI or by URL), summarised by an LLM, tagged against a taxonomy you control, and kept with full history in OpenSearch so you can search and re-process them later. You can also write your own thoughts straight into it; they are tagged and searched the same way.

- **Capture** a page from your browser (the extension sends what you see, so logins and consent walls are no problem) or by URL.
- **Summarise and tag** with any OpenAI-compatible LLM. Tags come only from your own taxonomy, and you have the last word on every Item's tags.
- **Search** with hybrid keyword + semantic search, filtered by tag, date and kind.
- **Keep history.** Capturing a page again adds a new Version instead of overwriting the old one.
- **Use it from an agent** through the built-in MCP server (Claude Code, or any other MCP client).

It runs on your own machine: a FastAPI app, OpenSearch in Docker, and your LLM API key. There is one user (the Owner), who signs in with a single token.

> **Status:** alpha, built for personal use. Done: capture, summarise, tag, embed and versioned storage; the web UI (browse, hybrid search, taxonomy editor); the browser extension; Thoughts; the MCP server. Next: an ease-of-use pass over the web UI, then automatic sources (RSS and similar). Data formats may still change between versions.

## How it works

```
browser extension ─┐
web UI ────────────┼─► FastAPI app ─► fetch ─► summarise ─► embed ─► tag ─► OpenSearch
HTTP API / MCP ────┘   (202 at once,   (crawl4ai,  (LLM)       (LLM)    (LLM,     (items + versions)
                        rest runs in    or HTML                          your
                        the background) from the browser)                taxonomy)
```

Each capture creates a new **Version** of an **Item** (one Item per normalised URL). The Version stores the LLM's summary, key points, tags and embedding, not the full page text. See [CONTEXT.md](CONTEXT.md) for the vocabulary and [docs/tagging.md](docs/tagging.md) for how tags are decided.

## Requirements

- Linux, macOS, or Windows with WSL2 (the setup script is Bash)
- [Docker](https://docs.docker.com/get-docker/) with the Compose plugin, for OpenSearch
- Python **3.12** (exactly 3.12; 3.13 is not supported yet)
- An API key for an OpenAI-compatible LLM endpoint (OpenAI by default; see [Configuration](#configuration))
- Node.js 22+, only if you want to build the browser extension

The default models (`gpt-4o-mini` and `text-embedding-3-small`) cost a fraction of a cent per captured page.

## Setup

**1. Clone the repository**

```bash
git clone https://github.com/podhoralukas/personal-knowledge-base.git
cd personal-knowledge-base
```

**2. Configure**

```bash
cp .env.example .env
```

Open `.env` and set two values:

- `API_TOKEN`: a long random secret. Every client (web UI, extension, API, MCP) signs in with it. Generate one with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
- `LLM_API_KEY`: your OpenAI API key (or the key for the endpoint you set in `LLM_BASE_URL`).

**3. Install and start OpenSearch**

```bash
./setup.sh
```

The script creates a `.venv` with Python 3.12, installs the package with its dev tools, starts OpenSearch and OpenSearch Dashboards with Docker Compose, and waits until OpenSearch is healthy. It is safe to run again. If you skipped step 2, it creates `.env` for you and stops so you can fill it in.

If `python3` on your machine is not 3.12, create the virtual environment yourself first; the script reuses an existing `.venv`:

```bash
python3.12 -m venv .venv
./setup.sh
```

The script installs the version ranges from `pyproject.toml`. To install the exact versions the project is tested with instead, use the pinned files:

```bash
.venv/bin/pip install -r requirements-dev.txt     # or requirements.txt without pytest and ruff
.venv/bin/pip install -e . --no-deps
docker compose up -d
```

**4. Start the app**

```bash
source .venv/bin/activate
uvicorn kb.app:app --reload
```

Open <http://localhost:8000> and sign in with your `API_TOKEN`. The OpenSearch indices are created on the first start.

To stop: `Ctrl+C` for the app, `docker compose stop` for OpenSearch. Your data lives in the `opensearch-data` Docker volume and survives restarts. `docker compose down -v` deletes it.

## Usage

### First steps

1. **Build your taxonomy.** Open **Taxonomy** and add a few tags, such as `ai`, `ai/agents`, `cooking`. Tags are lowercase paths; a child (`ai/agents`) is found by a filter on its parent (`ai`). A short description helps the LLM choose. **Until the taxonomy has tags, captures are summarised but not tagged.**
2. **Capture a page.** On **Items**, paste a URL and press capture. The Item appears at once as *pending* and fills in a few seconds later.
3. **Write a Thought.** Use the Thought form on **Items** for your own text without a URL. It is shown at once, then tagged and embedded in the background. Thoughts are never summarised.
4. **Search.** **Search** combines keyword and semantic matching and can be filtered by tag, date and kind (article or thought).

### Web UI

| Page | What you do there |
|---|---|
| **Items** | Capture a URL, write a Thought, browse everything, filter by tag, date range and kind; *untagged* lists Items no tag fitted. |
| **Item** | Read the summary and key points, add or remove tags, write a Note (private, never sent to the LLM), browse and delete Versions, retry a failed capture, edit a Thought. |
| **Search** | Hybrid search with the same filters. |
| **Taxonomy** | Add, describe, rename, move and delete tags. **Re-tag** runs the LLM again over untagged Items and Items that could use a new, more specific tag (or over every Item, after confirmation). |
| **API** | Interactive OpenAPI docs (`/docs`). |

When you remove a tag from an Item, the LLM is never offered that tag for that Item again. Re-tagging only adds tags. The full rules are in [docs/tagging.md](docs/tagging.md).

### Browser extension

The extension captures the page you are reading from your own browser, so consent walls, logins and bot checks you have already passed don't get in the way. It sends the article as Reader View would show it ([Mozilla Readability](https://github.com/mozilla/readability)), or the whole page when it finds no article.

Build it once:

```bash
cd extension
npm install
npm run build        # → extension/dist (npm run watch rebuilds on change)
```

Load `extension/dist` unpacked:

- **Chrome / Edge / Brave:** `chrome://extensions` → *Developer mode* → *Load unpacked* → pick `extension/dist`.
- **Firefox (128+):** `about:debugging#/runtime/this-firefox` → *Load Temporary Add-on…* → pick `extension/dist/manifest.json`. Temporary add-ons are removed when Firefox restarts.

Open the extension's options, set the server URL (default `http://localhost:8000`) and your `API_TOKEN`, and save; it tests the connection.

To capture, click the toolbar icon (or press `Alt+Shift+K`). Optionally tick tags (with none ticked, the server tags the page automatically) and write a Note (only for you, never sent to the LLM). Then press *Capture* or `Ctrl+Enter`. The Note is appended to the Item's Note, which you can edit later on the Item page.

### MCP server (agents)

The app serves an MCP endpoint at `/mcp` (streamable HTTP, protected by the same `API_TOKEN` bearer token), so an AI chat can use your knowledge base. It offers four tools:

- `search`: the search page's query and filters
- `write_thought`: save a Thought
- `tag_item`: add one of your tags to an Item (only when you ask it to)
- `list_tags`: read the taxonomy

To register it in [Claude Code](https://docs.claude.com/en/docs/claude-code) while the app runs:

```bash
claude mcp add --transport http kb http://localhost:8000/mcp --header "Authorization: Bearer $API_TOKEN"
```

Then ask, for example, "what do I have on Hamilton from this week?" or "save this as a Thought". Each search embeds your query (one embedding call). A written Thought is tagged and embedded in the background, as it is from the UI.

### HTTP API

Every endpoint needs `Authorization: Bearer $API_TOKEN`. The full reference is at <http://localhost:8000/docs>. A few examples (run `export API_TOKEN=...` first):

```bash
# Capture a page; returns at once, enrichment runs in the background
curl -X POST localhost:8000/capture \
  -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/some-article", "channel": "manual"}'
# → 202 {"item_id": "...", "version_id": "..."}

curl -H "Authorization: Bearer $API_TOKEN" localhost:8000/versions/<version_id>   # status: pending → enriched
curl -H "Authorization: Bearer $API_TOKEN" localhost:8000/items/<item_id>

# Write a Thought; `tags` picks tags yourself (skips auto-tagging), `written_at` makes retries idempotent
curl -X POST localhost:8000/thoughts \
  -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" \
  -d '{"title": "Optional", "text": "What I am thinking."}'

# Edit a Thought (adds a Version), delete one Version (409 if it is the last one), search
curl -X PUT localhost:8000/thoughts/<item_id> -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" -d '{"text": "Edited."}'
curl -X DELETE -H "Authorization: Bearer $API_TOKEN" localhost:8000/versions/<version_id>
curl -H "Authorization: Bearer $API_TOKEN" "localhost:8000/search?q=soup&kind=thought"   # kind: article | thought
```

Sending `content` (the page's HTML) in a capture skips the server-side fetch; that is what the browser extension does.

## Configuration

All settings are read from `.env` (see [.env.example](.env.example)) or from environment variables.

| Variable | Default | Description |
|---|---|---|
| `API_TOKEN` | none | **Required.** The token every client must send. Unset, every request is rejected. |
| `LLM_API_KEY` | none | **Required.** `OPENAI_API_KEY` is accepted as an alias. |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible endpoint that supports structured outputs. |
| `LLM_MODEL` | `gpt-4o-mini` | Model for summarising and tagging. |
| `EMBEDDING_BASE_URL` | `https://api.openai.com/v1` | Embeddings may use a different endpoint than chat. |
| `EMBEDDING_API_KEY` | `LLM_API_KEY` | |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Must return **1536-dimensional** vectors. Changing it makes existing vectors incomparable. |
| `OPENSEARCH_URL` | `http://localhost:9200` | OpenSearch endpoint. |
| `OPENSEARCH_USERNAME` / `OPENSEARCH_PASSWORD` | none | For a secured OpenSearch cluster. |
| `OPENSEARCH_INDEX_PREFIX` | empty | Prefix for index names, to keep several instances in one cluster apart. |

Fixed tunables (timeouts, search weights, length limits) are constants in [kb/config.py](kb/config.py).

## Security

This is a single-user app meant to run on your own machine.

- `uvicorn` listens on `127.0.0.1` by default. If you expose it beyond localhost, put it behind HTTPS (a reverse proxy) and use a strong `API_TOKEN`.
- The bundled `docker-compose.yml` runs OpenSearch **with its security plugin disabled** and publishes ports 9200 and 5601 on the host. Don't expose it to an untrusted network.
- Captured page content and your Thoughts are sent to the configured LLM provider. Notes are never sent.

## Troubleshooting

- **OpenSearch won't start, or the setup script keeps waiting.** Check `docker compose logs opensearch`. On Linux and WSL2, OpenSearch may need a larger memory-map limit: `sudo sysctl -w vm.max_map_count=262144`.
- **Every request returns 401.** `API_TOKEN` is unset or still `change-me`, or the client sends a different token. Restart the app after changing `.env`.
- **Items stay unsummarised or show an error.** Check the app's log for the LLM error (usually a wrong `LLM_API_KEY` or model name), then use *Retry* on the Item page.
- **Captures are never tagged.** The taxonomy is empty, or no tag fits. Add tags on the Taxonomy page and run *Re-tag*.
- **`pip install` fails with a Python version error.** The project needs Python 3.12; see step 3 of [Setup](#setup).
- **A page fails to fetch by URL.** Some sites block server-side requests. Capture it with the browser extension instead.

OpenSearch Dashboards at <http://localhost:5601> lets you look at the raw `items` and `versions` indices.

## Development

```bash
.venv/bin/pytest -q                                   # offline; see below
.venv/bin/ruff format . && .venv/bin/ruff check .
cd extension && npm test && npm run typecheck
```

The tests never call a real LLM: every response is mocked (`kb.llm.fake.FakeLLM`), and the API keys from `.env` are replaced with a fake one. Storage tests run against OpenSearch on `localhost:9200` when it is up (using a `test_` index prefix they clean up after themselves) and are skipped otherwise. Contributor and agent conventions are in [AGENTS.md](AGENTS.md).

### Project structure

```
kb/
  app.py              # FastAPI app: JSON API, mounts the web UI and the MCP server
  ui.py               # web UI (Jinja templates + htmx) behind a login cookie
  mcp_server.py       # MCP tools for agents
  auth.py             # the single Owner token
  config.py           # constants + Settings (env)
  models.py           # request and stored models: Item, Version, Enrichment, Taxonomy, ...
  normalize.py        # URL normalisation, item_id / thought_id / version_id
  search.py           # hybrid search
  taxonomy.py         # tag add / rename / delete, re-tag targets
  owner_tags.py       # the Owner's own and rejected tags on an Item
  notes.py            # the Owner's Note on an Item
  versions.py         # deleting a single Version
  pipeline/
    fetch.py          # crawl4ai fetch; browser HTML → markdown
    summarise.py      # structured LLM summary
    tag.py            # LLM tagging against the taxonomy
    run.py            # capture / write / edit / enrich: hash → reuse → summarise → embed → tag → store
  llm/                # LLMClient over any OpenAI-compatible endpoint; FakeLLM for tests
  storage/            # Storage protocol; OpenSearch + in-memory implementations; index mappings
  templates/, static/ # web UI
extension/            # browser extension (TypeScript, MV3, Chrome + Firefox); builds to extension/dist
tests/                # pytest
docs/                 # design plan, tagging model, ADRs
docker-compose.yml    # OpenSearch + Dashboards
setup.sh              # one-shot local setup
```

### Design documents

- [docs/plan.md](docs/plan.md): design and decisions
- [CONTEXT.md](CONTEXT.md): vocabulary (Item, Version, Capture, Thought, Tag, ...)
- [docs/tagging.md](docs/tagging.md): how tags are proposed, kept and rejected
- [docs/adr/](docs/adr/): architecture decision records

## Credits

This product includes software developed by UncleCode (https://x.com/unclecode) as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai).

The web UI ships [htmx](https://htmx.org) (0BSD) in `kb/static/`. The browser extension bundles [Mozilla Readability](https://github.com/mozilla/readability) (Apache-2.0) into its build. Every other dependency is installed from PyPI or npm under its own license.

## License

The code in this repository is released under the [MIT License](LICENSE). Dependencies keep their own licenses.
