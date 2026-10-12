"""HTTP ingress. Run with: uvicorn kb.app:app --reload"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.routing import Route

from kb.auth import valid_token
from kb.config import EXTENSION_ORIGINS, MCP_PATH, NOTE_MAX_CHARS, STATIC_DIR, Settings, get_settings
from kb.llm import LLMClient
from kb.mcp_server import Background, BearerGuard, mcp_server
from kb.models import (
    CaptureRequest,
    DateRange,
    Item,
    Kind,
    Tag,
    Taxonomy,
    ThoughtEdit,
    ThoughtRequest,
    Version,
    VersionStatus,
)
from kb.notes import write_note
from kb.owner_tags import allow_tag, tag_item, untag_item
from kb.pipeline.fetch import FetchError
from kb.pipeline.run import Pipeline
from kb.search import SearchResults, search
from kb.storage import TagExists
from kb.storage.opensearch import OpenSearchStorage
from kb.taxonomy import TagNotFound, add_tag, delete_tag, describe_tag, rename_tag, retag_targets
from kb.ui import ui_router
from kb.versions import LastVersion, delete_version

log = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


class Accepted(BaseModel):
    item_id: str
    version_id: str


class NewTag(BaseModel):
    path: str
    description: str = ""


class TagChange(BaseModel):
    """Either or both: a new description, a new path (a rename or move: spelling, not meaning)."""

    description: str | None = None
    path: str | None = None


class OwnerTag(BaseModel):
    path: str


class Note(BaseModel):
    notes: str = Field(max_length=NOTE_MAX_CHARS)


class RetagAccepted(BaseModel):
    taxonomy_version: int
    item_count: int


def create_app(settings: Settings | None = None, pipeline: Pipeline | None = None) -> FastAPI:
    """`pipeline` is injected by tests; in production it is built from settings on startup."""
    settings = settings or get_settings()
    agents = mcp_server(lambda: app.state.pipeline, Background())
    mcp_endpoint = agents.streamable_http_app().routes[0].endpoint

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if pipeline is None:
            storage = OpenSearchStorage.from_settings(settings)
            storage.ensure_indices()
            app.state.pipeline = Pipeline(storage, LLMClient.from_settings(settings))
        else:
            app.state.pipeline = pipeline
        if not settings.api_token:
            log.warning("API_TOKEN is not set: every request will be rejected")
        async with agents.session_manager.run():
            yield

    app = FastAPI(title="Knowledge Base", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=EXTENSION_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def authenticated(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> None:
        if not valid_token(settings.api_token, credentials.credentials if credentials else None):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing bearer token")

    def get_pipeline(request: Request) -> Pipeline:
        return request.app.state.pipeline

    Auth = Annotated[None, Depends(authenticated)]
    Pipe = Annotated[Pipeline, Depends(get_pipeline)]

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(ui_router(settings))
    app.router.routes.append(Route(MCP_PATH, BearerGuard(mcp_endpoint, settings.api_token)))

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/ui", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/capture", status_code=status.HTTP_202_ACCEPTED, response_model=Accepted)
    async def capture(request: CaptureRequest, background: BackgroundTasks, pipe: Pipe, _: Auth) -> Accepted:
        try:
            version = await pipe.capture(request)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
        except FetchError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"fetch failed: {exc}")
        background.add_task(pipe.enrich, version)
        return Accepted(item_id=version.item_id, version_id=version.id)

    def enriching(version: Version | None, background: BackgroundTasks, pipe: Pipeline) -> Accepted:
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such item")
        if version.status is VersionStatus.PENDING:
            background.add_task(pipe.enrich, version)
        return Accepted(item_id=version.item_id, version_id=version.id)

    @app.post("/thoughts", status_code=status.HTTP_202_ACCEPTED, response_model=Accepted)
    def write_thought(thought: ThoughtRequest, background: BackgroundTasks, pipe: Pipe, _: Auth) -> Accepted:
        """Shown at once; tags and embedding follow in the background."""
        try:
            return enriching(pipe.write(thought), background, pipe)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    @app.put("/thoughts/{item_id}", status_code=status.HTTP_202_ACCEPTED, response_model=Accepted)
    def edit_thought(item_id: str, thought: ThoughtEdit, background: BackgroundTasks, pipe: Pipe, _: Auth) -> Accepted:
        """Adds a Version of the Thought."""
        try:
            return enriching(pipe.edit(item_id, thought), background, pipe)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    @app.post("/thoughts/{item_id}/retry", status_code=status.HTTP_202_ACCEPTED, response_model=Accepted)
    def retry_thought(item_id: str, background: BackgroundTasks, pipe: Pipe, _: Auth) -> Accepted:
        """Enrich the Thought's failed current Version again."""
        try:
            return enriching(pipe.retry(item_id), background, pipe)
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc))

    @app.get("/search", response_model=SearchResults)
    async def search_items(
        q: Annotated[str, Query(min_length=1)],
        pipe: Pipe,
        _: Auth,
        tag: str | None = None,
        start: Annotated[date | None, Query(alias="from", description="Saved on or after (UTC day)")] = None,
        end: Annotated[date | None, Query(alias="to", description="Saved on or before (UTC day)")] = None,
        kind: Kind | None = None,
    ) -> SearchResults:
        try:
            saved = DateRange(start=start, end=end)
        except ValidationError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors()[0]["msg"].removeprefix("Value error, ")
            )
        return await search(pipe.storage, pipe.llm, q, tag, saved, kind)

    @app.get("/items/untagged", response_model=list[Item])
    def list_untagged(pipe: Pipe, _: Auth, kind: Kind | None = None) -> list[Item]:
        return pipe.storage.list_untagged_items(kind=kind)

    @app.get("/items/{item_id}", response_model=Item)
    def get_item(item_id: str, pipe: Pipe, _: Auth) -> Item:
        item = pipe.storage.get_item(item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such item")
        return item

    @app.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_item(item_id: str, pipe: Pipe, _: Auth) -> None:
        """Delete the Item with its whole Version history."""
        if not pipe.storage.delete_item(item_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such item")

    def edited(item: Item | None) -> Item:
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such item")
        return item

    @app.post("/items/{item_id}/tags", response_model=Item)
    def add_owner_tag(item_id: str, body: OwnerTag, pipe: Pipe, _: Auth) -> Item:
        """Tag the Item by hand; the tag survives new Captures and re-tags."""
        try:
            return edited(tag_item(pipe.storage, item_id, body.path))
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    @app.delete("/items/{item_id}/tags/{path:path}", response_model=Item)
    def untag(item_id: str, path: str, pipe: Pipe, _: Auth) -> Item:
        """Take the tag off the Item; it stays rejected for this Item until allowed again."""
        try:
            return edited(untag_item(pipe.storage, item_id, path))
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    @app.delete("/items/{item_id}/rejected-tags/{path:path}", response_model=Item)
    def allow_again(item_id: str, path: str, pipe: Pipe, _: Auth) -> Item:
        """Let the pipeline choose a rejected tag for this Item again."""
        try:
            return edited(allow_tag(pipe.storage, item_id, path))
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    @app.put("/items/{item_id}/notes", response_model=Item)
    def put_note(item_id: str, body: Note, pipe: Pipe, _: Auth) -> Item:
        """Replace the Item's Note; an empty one clears it. A Thought has no Note."""
        try:
            return edited(write_note(pipe.storage, item_id, body.notes))
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    @app.get("/items/{item_id}/versions", response_model=list[Version])
    def list_versions(item_id: str, pipe: Pipe, _: Auth) -> list[Version]:
        return pipe.storage.list_versions(item_id)

    @app.get("/versions/{version_id}", response_model=Version)
    def get_version(version_id: str, pipe: Pipe, _: Auth) -> Version:
        version = pipe.storage.get_version(version_id)
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such version")
        return version

    @app.delete("/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_version(version_id: str, pipe: Pipe, _: Auth) -> None:
        """The Item then shows its newest remaining Version; its last one cannot be deleted."""
        try:
            deleted = delete_version(pipe.storage, version_id)
        except LastVersion as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
        if not deleted:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such version")

    @app.get("/taxonomy", response_model=Taxonomy)
    def get_taxonomy(pipe: Pipe, _: Auth) -> Taxonomy:
        return pipe.storage.get_taxonomy()

    @app.post("/taxonomy/tags", status_code=status.HTTP_201_CREATED, response_model=Tag)
    def create_tag(body: NewTag, pipe: Pipe, _: Auth) -> Tag:
        try:
            return add_tag(pipe.storage, body.path, body.description)
        except TagExists:
            raise HTTPException(status.HTTP_409_CONFLICT, f"tag {body.path!r} already exists")
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    @app.patch("/taxonomy/tags/{path:path}", response_model=Tag)
    def change_tag(path: str, body: TagChange, pipe: Pipe, _: Auth) -> Tag:
        """Edit the description and/or rename the Tag; a rename applies to its sub-tags, Items and Versions."""
        current = path
        try:
            if body.path is not None and body.path != path:
                current = rename_tag(pipe.storage, path, body.path).path
            if body.description is not None:
                describe_tag(pipe.storage, current, body.description)
        except TagNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no tag {path!r}")
        except TagExists:
            raise HTTPException(status.HTTP_409_CONFLICT, f"tag {body.path!r} already exists")
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
        tag = pipe.storage.get_taxonomy().get(current)
        if tag is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no tag {path!r}")
        return tag

    @app.delete("/taxonomy/tags/{path:path}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_tag(path: str, pipe: Pipe, _: Auth) -> None:
        """Only a Tag nothing uses and without sub-tags."""
        try:
            delete_tag(pipe.storage, path)
        except TagNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no tag {path!r}")
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc))

    @app.post("/taxonomy/retag", status_code=status.HTTP_202_ACCEPTED, response_model=RetagAccepted)
    def retag(
        background: BackgroundTasks, pipe: Pipe, _: Auth, every_item: Annotated[bool, Query(alias="all")] = False
    ) -> RetagAccepted:
        """Re-tag untagged Items and Items tagged with an ancestor of a new Tag, or every Item with `all=true`.
        Re-tags only add tags."""
        item_ids = retag_targets(pipe.storage, every_item)
        background.add_task(pipe.retag_all, item_ids)
        return RetagAccepted(taxonomy_version=pipe.storage.get_taxonomy().version, item_count=len(item_ids))

    return app


app = create_app()
