"""Constants shared across the package, and runtime settings read from the environment."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# URL normalisation
TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "twclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "yclid",
        "_hsenc",
        "_hsmi",
        "ref",
        "ref_src",
    }
)
TRACKING_PREFIXES = ("utm_",)
DEFAULT_PORTS = {"http": 80, "https": 443}

# Timestamps: UTC, millisecond precision, e.g. 2026-09-21T14:03:05.123Z
CAPTURED_AT_FORMAT = "%Y-%m-%dT%H:%M:%S.{ms:03d}Z"

# Server-side fetch
FETCH_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 kb/2.0"
)
FETCH_TIMEOUT_MS = 15000
FETCH_EXCLUDED_TAGS = ["nav", "header", "footer"]

# Taxonomy: lowercase slug segments joined by "/", e.g. ai/retrieval/rag
TAG_SEGMENT_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)*"
TAG_PATH_PATTERN = rf"{TAG_SEGMENT_PATTERN}(?:/{TAG_SEGMENT_PATTERN})*"
TAXONOMY_META_ID = "_meta"
TAXONOMY_MAX_TAGS = 10_000

# The Owner's Note on an Item, and the part of it sent with one Capture
NOTE_MAX_CHARS = 20_000

# Thoughts: text the Owner writes. The pipeline reads only the start of a long one; an empty title
# becomes the first line of the text, cut to the derived length.
THOUGHT_ID_PREFIX = "thought:"
THOUGHT_MAX_CHARS = 20_000
THOUGHT_TITLE_MAX_CHARS = 200
THOUGHT_DERIVED_TITLE_CHARS = 80
THOUGHT_PIPELINE_MAX_CHARS = 8_000

# Listings that return whole Items
LIST_MAX_ITEMS = 1000

# Hybrid search: BM25 over these fields + k-NN over the embedding, min-max normalised and averaged
SEARCH_PIPELINE = "kb-hybrid"
SEARCH_FIELDS = ["title^2", "summary", "key_points", "text", "annotations.notes"]
SEARCH_KEYWORD_WEIGHT = 0.5
SEARCH_VECTOR_WEIGHT = 0.5
SEARCH_KNN_K = 50
SEARCH_RESULTS = 20

# Web UI
PACKAGE_DIR = Path(__file__).parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
UI_TOKEN_COOKIE = "kb_token"
UI_TOKEN_COOKIE_MAX_AGE = 60 * 60 * 24 * 30
UI_PENDING_POLL = "2s"

# React app: built by `npm run build` in web/ and served by the app. It sends the login cookie to the JSON
# API; a cookie-authenticated request must also carry this header, which another site cannot add.
WEB_PATH = "/app"
WEB_DIST_DIR = PACKAGE_DIR.parent / "web" / "dist"
CSRF_HEADER = "X-KB-CSRF"

# MCP server for agents, mounted in the app; a search result carries only the start of a long Thought
MCP_PATH = "/mcp"
MCP_THOUGHT_TEXT_CHARS = 2_000

# Browser extension: its pages call the JSON API cross-origin
EXTENSION_ORIGINS = r"^(chrome-extension|moz-extension)://[a-z0-9-]+$"

# LLM
LLM_TEMPERATURE = 0
EMBEDDING_DIM = 1536
SUMMARY_INPUT_MAX_CHARS = 24_000


class Settings(BaseSettings):
    """Runtime configuration from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Static bearer token the extension / clients must send. Unset = every request is rejected.
    api_token: str | None = None

    opensearch_url: str = "http://localhost:9200"
    opensearch_username: str | None = None
    opensearch_password: str | None = None
    opensearch_index_prefix: str = ""

    # Any OpenAI-compatible endpoint (OpenAI, Anthropic, Ollama, Gemini, Mistral, ...).
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = Field(default=None, validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"))
    llm_model: str = "gpt-4o-mini"
    # Embeddings may come from a different endpoint (e.g. Claude for chat, OpenAI or Ollama for vectors).
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("EMBEDDING_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")
    )
    embedding_model: str = "text-embedding-3-small"


@lru_cache
def get_settings() -> Settings:
    return Settings()
