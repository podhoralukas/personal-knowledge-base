Experimental, locally self-hosted solution to store information of your interest from the internet articles you browse, with the possibility to enhance them with your custom thoughts.

The problem which I tried to solve for myself - I read lots of super-interesting internet content and articles, but after a week or so, I just don't remember where it was :).  Thus, by hitting the single button in the browser extension, the article gets summarized and saved into my personal "diary", and gets sorted into the relevant category. The single keyword or sentence in search box then finds it for me. I can also use my personal AI assistant for that. 


The website content is captured via the browser extension (Chrome/Firefox) and Crawl4AI engine, shortened and summarized using LLM API call. Then it's saved to the OpenSearch database, vectorized and pre-selected tags are applied. The search engine uses combination of keyword and semantic search. The app also contains the MCP server with search and tagging tools, enabling connection to any chat interface you use. 

The app uses manually added system of tags, which you should manually define before using (the tags can be also added later)- e.g. categories to which you would like to split the information into. The article is then automatically tagged at capture.  Each article is versioned by the date it was captured. The search engine then enables for selecting the relevant information by date. 

Each capture uses single LLM API call to summarize the information for storing, and then another one to construct the vector for semantic search. Your custom OpenAI API key has to be added to the env variables once running locally. 

Extent of use of AI to create this app - Claude Code was used to write the code. The domain design and architectural decisions were done by myself. 

### Possible next development steps:
- enhancing UI of the taxonomy and search interface so that it is clearer,
- adding the possibility to modify the system prompt at the extension input,
- hosting of OpenSearch db and the app container in cloud.

---

*The app setup description below is AI-generated.*

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
- [Docker](https://docs.docker.com/get-docker/) with the Compose plugin (Docker Desktop on Windows), which runs OpenSearch and the app
- Python **3.12** (exactly 3.12; 3.13 is not supported yet), for the tests and the setup script's tooling
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

**3. Install and start**

```bash
./setup.sh
```

The script creates a `.venv` with Python 3.12 for the tests, builds and starts OpenSearch and the app with Docker Compose, waits until the app is up, and configures backups (see [Backups](#backups)). It is safe to run again. If you skipped step 2, it creates `.env` for you and stops so you can fill it in.

If `python3` on your machine is not 3.12, create the virtual environment yourself first; the script reuses an existing `.venv`:

```bash
python3.12 -m venv .venv
./setup.sh
```

Open <http://localhost:8000> and sign in with your `API_TOKEN`. The OpenSearch indices are created when the app first starts.

**4. Keep it running**

Both containers (`kb-opensearch`, `kb-app`) restart whenever Docker does. On Windows, turn on Docker Desktop's *Settings → General → Start Docker Desktop when you sign in*, and the Knowledge Base is up a minute after you sign in, without opening a terminal.

To stop it: `docker compose stop` (it stays stopped until `docker compose start`). Your data lives in the `kb_opensearch-data` Docker volume and survives restarts. `docker compose down -v` deletes it.

### Development

The app container runs the source from this folder with `uvicorn --reload`, so a change in `kb/` is live within a second; a broken edit stops the app until it is fixed (`docker compose logs -f app`). After changing dependencies in `pyproject.toml`, rebuild with `docker compose up -d --build`. Tests run from the `.venv` (`.venv/bin/pytest`); the OpenSearch tests use `test_`-prefixed indices in the same cluster and delete them afterwards.

### Backups

OpenSearch snapshots the Knowledge Base's indices every 2 hours into the folder `KB_BACKUP_DIR` (default `./backups`) and keeps them for 14 days. Point it at a folder that leaves the machine, e.g. `C:\Users\<you>\kb-backups` (`KB_BACKUP_DIR=/mnt/c/Users/<you>/kb-backups` under WSL) synced by Google Drive for desktop (*Preferences → My Computer → Add folder*) or OneDrive. Snapshots are incremental, so they stay small.

To restore one (here into renamed indices, to compare before replacing anything):

```bash
curl -s localhost:9201/_snapshot/kb-backups/_all | python3 -m json.tool   # list snapshots
curl -X POST "localhost:9201/_snapshot/kb-backups/<snapshot>/_restore" -H 'Content-Type: application/json' \
  -d '{"indices": "items,versions,taxonomy", "rename_pattern": "(.+)", "rename_replacement": "restored-$1"}'
```

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

The full API is described in the OpenAPI (Swagger) spec at <http://localhost:8000/openapi.json>, browsable at <http://localhost:8000/docs>. Every endpoint needs `Authorization: Bearer $API_TOKEN`.

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
| `OPENSEARCH_URL` | `http://localhost:9200` | OpenSearch endpoint. `docker-compose.yml` sets it to the `kb-opensearch` container for the app. |
| `OPENSEARCH_USERNAME` / `OPENSEARCH_PASSWORD` | none | For a secured OpenSearch cluster. |
| `OPENSEARCH_INDEX_PREFIX` | empty | Prefix for index names, to keep several instances in one cluster apart. |
| `KB_BACKUP_DIR` | `./backups` | Folder for OpenSearch snapshots, read by `docker-compose.yml`. |

Fixed tunables (timeouts, search weights, length limits) are constants in [kb/config.py](kb/config.py).

## Security

This is a single-user app meant to run on your own machine.

- `docker-compose.yml` publishes the app (port 8000) and OpenSearch (port 9201) on `127.0.0.1` only. If you expose the app beyond localhost, put it behind HTTPS (a reverse proxy or a tunnel) and use a strong `API_TOKEN`.
- OpenSearch runs **with its security plugin disabled**. Never publish port 9201 to a network.
- Captured page content and your Thoughts are sent to the configured LLM provider. Notes are never sent.


### Design documents

- [CONTEXT.md](CONTEXT.md): vocabulary (Item, Version, Capture, Thought, Tag, ...)
- [docs/tagging.md](docs/tagging.md): how tags are proposed, kept and rejected
- [docs/adr/](docs/adr/): architecture decision records

## Credits

This product includes software developed by UncleCode (https://x.com/unclecode) as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai).

The web UI ships [htmx](https://htmx.org) (0BSD) in `kb/static/`. The browser extension bundles [Mozilla Readability](https://github.com/mozilla/readability) (Apache-2.0) into its build. Every other dependency is installed from PyPI or npm under its own license.

## License

The code in this repository is released under the [MIT License](LICENSE). Dependencies keep their own licenses.
