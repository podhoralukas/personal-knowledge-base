"""MCP server for agents acting for the Owner: search, write a Thought, tag an Item, list the Taxonomy."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import date, datetime
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field, ValidationError
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from kb.auth import valid_token
from kb.config import MCP_PATH, MCP_THOUGHT_TEXT_CHARS
from kb.models import Channel, DateRange, Kind, Match, ThoughtRequest
from kb.owner_tags import tag_item as add_owner_tag
from kb.pipeline.run import Pipeline
from kb.search import search as hybrid_search

log = logging.getLogger(__name__)

INSTRUCTIONS = """The Owner's personal knowledge base: articles they saved and Thoughts they wrote, tagged against \
their own Taxonomy. Search it when the Owner asks what they have on a topic. Write a Thought only when the Owner \
asks to save something. Tag an Item only when the Owner explicitly asks for that tag."""


class Found(BaseModel):
    item_id: str
    kind: Kind
    title: str
    tags: list[str]
    saved_at: datetime
    url: str | None = Field(description="The article's source; none for a Thought")
    score: float = Field(description="Relative to the other results of this search; low ones are likely unrelated")
    link: str = Field(description="The Item's page in the Owner's web UI")
    note: str = Field(description="The Owner's own note on the article")
    summary: str = Field(description="An article's summary")
    key_points: list[str]
    text: str = Field(description="A Thought's text; a long one ends with … and continues on its page")

    @classmethod
    def of(cls, match: Match, base_url: str) -> "Found":
        text = match.text or ""
        return cls(
            item_id=match.id,
            kind=match.media_type,
            title=match.title,
            tags=match.tags,
            saved_at=match.first_captured_at,
            url=match.original_url,
            score=round(match.score, 3),
            link=item_link(base_url, match.id),
            note=match.annotations.notes,
            summary=match.summary,
            key_points=match.key_points,
            text=text if len(text) <= MCP_THOUGHT_TEXT_CHARS else text[:MCP_THOUGHT_TEXT_CHARS] + "…",
        )


class SearchResult(BaseModel):
    items: list[Found] = Field(description="Best match first")
    semantic: bool = Field(description="False when only keywords were matched, not meaning")


class Written(BaseModel):
    item_id: str
    link: str


class Tagged(BaseModel):
    item_id: str
    tags: list[str] = Field(description="All the Item's tags after the change")


class TagInfo(BaseModel):
    path: str
    description: str


class TagList(BaseModel):
    tags: list[TagInfo]


class Background:
    """Enrichment started by a tool call; it outlives the call, like FastAPI's background tasks."""

    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()

    def start(self, work: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(work)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def wait(self) -> None:
        await asyncio.gather(*self.tasks)


class BearerGuard:
    """The JSON API's bearer check in front of the MCP endpoint."""

    def __init__(self, app: ASGIApp, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scheme, _, given = Headers(scope=scope).get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not valid_token(self.token, given):
            response = JSONResponse({"detail": "invalid or missing bearer token"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def item_link(base_url: str, item_id: str) -> str:
    return f"{base_url.rstrip('/')}/open/items/{item_id}"


def mcp_server(pipeline: Callable[[], Pipeline], background: Background) -> FastMCP:
    """`pipeline` is read per call: the app builds it on startup."""
    server = FastMCP(
        "Knowledge Base",
        instructions=INSTRUCTIONS,
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
    )

    def base_url(ctx: Context) -> str:
        request = ctx.request_context.request
        return str(request.base_url) if request is not None else ""

    def known_tag(pipe: Pipeline, tag: str) -> None:
        if pipe.storage.get_taxonomy().get(tag) is None:
            raise ToolError(f"tag {tag!r} is not in the taxonomy; call list_tags for the valid paths")

    @server.tool()
    async def search(
        query: Annotated[str, Field(min_length=1)],
        ctx: Context,
        tag: Annotated[str | None, Field(description="A Tag path from list_tags; sub-tags included")] = None,
        kind: Kind | None = None,
        saved_from: Annotated[date | None, Field(description="Saved on or after this UTC day")] = None,
        saved_to: Annotated[date | None, Field(description="Saved on or before this UTC day")] = None,
    ) -> SearchResult:
        """Search the Owner's knowledge base by keywords and meaning, as the search page does: the 20 best
        Items, narrowed by tag, kind and saved date when given. There is no relevance cutoff, so the last
        results may be unrelated: judge by score and content."""
        pipe = pipeline()
        if tag is not None:
            known_tag(pipe, tag)
        try:
            saved = DateRange(start=saved_from, end=saved_to)
        except ValidationError as exc:
            raise ToolError(exc.errors()[0]["msg"].removeprefix("Value error, "))
        results = await hybrid_search(pipe.storage, pipe.llm, query, tag, saved, kind)
        base = base_url(ctx)
        return SearchResult(items=[Found.of(m, base) for m in results.items], semantic=results.semantic)

    @server.tool()
    def write_thought(text: str, ctx: Context, title: str = "") -> Written:
        """Save a Thought for the Owner: plain text with an optional title (else its first line). Use it only
        when the Owner asks to save something. It is searchable by keywords at once; tags and search by
        meaning follow within seconds."""
        pipe = pipeline()
        try:
            thought = ThoughtRequest(title=title, text=text)
        except ValidationError as exc:
            raise ToolError(exc.errors()[0]["msg"].removeprefix("Value error, "))
        version = pipe.write(thought, Channel.MCP)
        background.start(pipe.enrich(version))
        return Written(item_id=version.item_id, link=item_link(base_url(ctx), version.item_id))

    @server.tool()
    def tag_item(item_id: str, tag: Annotated[str, Field(description="A Tag path from list_tags")]) -> Tagged:
        """Add a Tag to an Item (an article or a Thought) as the Owner's own choice; it stays through later
        captures and re-tags. Use it only when the Owner explicitly asks to tag something."""
        pipe = pipeline()
        known_tag(pipe, tag)
        item = add_owner_tag(pipe.storage, item_id, tag)
        if item is None:
            raise ToolError(f"no item {item_id!r}")
        return Tagged(item_id=item.id, tags=item.tags)

    @server.tool()
    def list_tags() -> TagList:
        """The Owner's Taxonomy: every Tag path (e.g. news/sport/formula1) with its description."""
        taxonomy = pipeline().storage.get_taxonomy()
        return TagList(tags=[TagInfo(path=t.path, description=t.description) for t in taxonomy.tags])

    return server
