"""Web UI: server-rendered pages (Jinja + htmx) behind a login cookie holding the Owner token."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, NamedTuple
from urllib.parse import quote, urlencode, urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from kb.auth import valid_token
from kb.config import (
    NOTE_MAX_CHARS,
    STATIC_DIR,
    TEMPLATES_DIR,
    UI_PENDING_POLL,
    UI_TOKEN_COOKIE,
    UI_TOKEN_COOKIE_MAX_AGE,
    Settings,
)
from kb.models import CaptureRequest, Channel, DateRange, Kind, Tag, ThoughtEdit, ThoughtRequest, VersionStatus
from kb.notes import write_note
from kb.owner_tags import allow_tag, tag_item, untag_item
from kb.pipeline.fetch import FetchError
from kb.pipeline.run import Pipeline
from kb.search import search
from kb.storage import TagExists
from kb.taxonomy import (
    TagNotFound,
    add_tag,
    deletable_tags,
    delete_tag,
    describe_tag,
    rename_tag,
    retag_targets,
)
from kb.versions import LastVersion, delete_version

templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["when"] = lambda dt: dt.strftime("%Y-%m-%d %H:%M UTC")
templates.env.filters["domain"] = lambda url: urlsplit(url).hostname or url
templates.env.filters["keep_filters"] = lambda url, request: keep_filters(url, request)
templates.env.globals["static_version"] = int((STATIC_DIR / "style.css").stat().st_mtime)  # busts browser caches


def ui_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/ui", include_in_schema=False, default_response_class=HTMLResponse)

    def logged_in(request: Request) -> None:
        if valid_token(settings.api_token, request.cookies.get(UI_TOKEN_COOKIE)):
            return
        login = f"/ui/login?next={quote(request.url.path)}"
        if request.headers.get("HX-Request"):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"HX-Redirect": login})
        raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": login})

    def get_pipeline(request: Request) -> Pipeline:
        return request.app.state.pipeline

    LoggedIn = Annotated[None, Depends(logged_in)]
    Pipe = Annotated[Pipeline, Depends(get_pipeline)]

    def page(request: Request, name: str, status_code: int = status.HTTP_200_OK, **context) -> HTMLResponse:
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    def not_found(request: Request, what: str) -> HTMLResponse:
        return page(request, "error.html", status.HTTP_404_NOT_FOUND, title="Not found", message=f"No such {what}.")

    @router.get("/login")
    def login_form(request: Request, next_url: Annotated[str, Query(alias="next")] = "/ui"):
        return page(request, "login.html", next=next_url)

    @router.post("/login")
    def login(request: Request, token: Annotated[str, Form()], next_url: Annotated[str, Form(alias="next")] = "/ui"):
        if not valid_token(settings.api_token, token):
            return page(request, "login.html", status.HTTP_401_UNAUTHORIZED, next=next_url, error="Wrong token.")
        response = RedirectResponse(safe_next(next_url), status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            UI_TOKEN_COOKIE,
            token,
            max_age=UI_TOKEN_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        return response

    @router.post("/logout")
    def logout():
        response = RedirectResponse("/ui/login", status.HTTP_303_SEE_OTHER)
        response.delete_cookie(UI_TOKEN_COOKIE)
        return response

    Start = Annotated[str, Query(alias="from")]
    End = Annotated[str, Query(alias="to")]

    def tag_paths(pipe: Pipeline) -> list[str]:
        return [t.path for t in pipe.storage.get_taxonomy().tags]

    def items_page(
        request: Request,
        pipe: Pipeline,
        status_code: int = status.HTTP_200_OK,
        tag: str | None = None,
        start: str = "",
        end: str = "",
        kind: str = "",
        **context,
    ):
        filters = date_filter(start, end) | kind_filter(kind)
        listed = pipe.storage.list_items(tag, filters["saved"], filters["kind"])
        return page(
            request, "items.html", status_code, items=listed, tag=tag, tags=tag_paths(pipe), **filters, **context
        )

    @router.get("")
    def items(
        request: Request,
        pipe: Pipe,
        _: LoggedIn,
        tag: str | None = None,
        start: Start = "",
        end: End = "",
        kind: str = "",
    ):
        return items_page(request, pipe, tag=tag, start=start, end=end, kind=kind)

    @router.get("/untagged")
    def untagged(request: Request, pipe: Pipe, _: LoggedIn, start: Start = "", end: End = "", kind: str = ""):
        filters = date_filter(start, end) | kind_filter(kind)
        items = pipe.storage.list_untagged_items(filters["saved"], filters["kind"])
        return page(request, "items.html", items=items, tag=None, untagged=True, **filters)

    @router.get("/search")
    async def search_page(
        request: Request,
        pipe: Pipe,
        _: LoggedIn,
        q: str = "",
        tag: str | None = None,
        start: Start = "",
        end: End = "",
        kind: str = "",
    ):
        tag = tag or None
        filters = date_filter(start, end) | kind_filter(kind)
        text = q.strip()
        results = await search(pipe.storage, pipe.llm, text, tag, filters["saved"], filters["kind"]) if text else None
        return page(request, "search.html", q=q, tag=tag, results=results, tags=tag_paths(pipe), **filters)

    @router.post("/capture")
    async def capture(
        request: Request, background: BackgroundTasks, pipe: Pipe, _: LoggedIn, url: Annotated[str, Form()]
    ):
        try:
            version = await pipe.capture(CaptureRequest(url=url.strip(), channel=Channel.MANUAL))
        except (ValueError, FetchError) as exc:
            code = status.HTTP_502_BAD_GATEWAY if isinstance(exc, FetchError) else status.HTTP_422_UNPROCESSABLE_CONTENT
            return items_page(request, pipe, code, error=f"Could not capture {url}: {exc}", url=url)
        background.add_task(pipe.enrich, version)
        return RedirectResponse(f"/ui/items/{version.item_id}", status.HTTP_303_SEE_OTHER)

    @router.post("/thoughts")
    def write_thought(
        request: Request,
        background: BackgroundTasks,
        pipe: Pipe,
        _: LoggedIn,
        text: Annotated[str, Form()] = "",
        title: Annotated[str, Form()] = "",
        tags: Annotated[list[str], Form()] = [],  # noqa: B006 - FastAPI copies form defaults
    ):
        draft = {"title": title, "text": text, "tags": tags}
        try:
            version = pipe.write(ThoughtRequest(**draft))
        except ValueError as exc:  # pydantic's ValidationError included
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
            return items_page(request, pipe, code, thought_error=thought_error(exc), thought_draft=draft)
        background.add_task(pipe.enrich, version)
        return RedirectResponse(f"/ui/items/{version.item_id}", status.HTTP_303_SEE_OTHER)

    def taxonomy_page(request: Request, pipe: Pipeline, status_code: int = status.HTTP_200_OK, **context):
        taxonomy = pipe.storage.get_taxonomy()
        return page(
            request,
            "taxonomy.html",
            status_code,
            version=taxonomy.version,
            tree=tag_tree(taxonomy.tags),
            counts=pipe.storage.count_items([t.path for t in taxonomy.tags]),
            deletable=deletable_tags(pipe.storage),
            untagged=len(pipe.storage.list_untagged_items()),
            candidates=len(retag_targets(pipe.storage)),
            total=len(pipe.storage.list_item_ids()),
            **{"done": {}, **context},
        )

    @router.get("/taxonomy")
    def taxonomy(
        request: Request,
        pipe: Pipe,
        _: LoggedIn,
        added: str | None = None,
        described: str | None = None,
        renamed: str | None = None,
        deleted: str | None = None,
        retagging: int | None = None,
    ):
        done = {"added": added, "described": described, "renamed": renamed, "deleted": deleted}
        return taxonomy_page(request, pipe, done={k: v for k, v in done.items() if v}, retagging=retagging)

    @router.post("/taxonomy/tags")
    def create_tag(
        request: Request,
        pipe: Pipe,
        _: LoggedIn,
        path: Annotated[str, Form()],
        description: Annotated[str, Form()] = "",
    ):
        path = path.strip()
        try:
            add_tag(pipe.storage, path, description)
        except TagExists:
            error, code = f"Tag {path} already exists.", status.HTTP_409_CONFLICT
        except ValueError as exc:
            error, code = str(exc), status.HTTP_422_UNPROCESSABLE_CONTENT
        else:
            return RedirectResponse(f"/ui/taxonomy?added={quote(path)}", status.HTTP_303_SEE_OTHER)
        return taxonomy_page(request, pipe, code, path=path, description=description, error=error)

    def tag_change(request: Request, pipe: Pipeline, change, done: str, *args: str):
        """Apply a Taxonomy change and return to the tree, or show the tree with the error."""
        try:
            result = change(pipe.storage, *args)
        except TagNotFound as exc:
            error, code = f"Tag {exc} does not exist.", status.HTTP_404_NOT_FOUND
        except TagExists as exc:
            error, code = f"Tag {exc} already exists.", status.HTTP_409_CONFLICT
        except ValueError as exc:
            error, code = str(exc), status.HTTP_422_UNPROCESSABLE_CONTENT
        else:
            path = result.path if isinstance(result, Tag) else args[0]
            return RedirectResponse(f"/ui/taxonomy?{done}={quote(path)}", status.HTTP_303_SEE_OTHER)
        return taxonomy_page(request, pipe, code, error=error)

    @router.post("/taxonomy/describe")
    def describe(
        request: Request,
        pipe: Pipe,
        _: LoggedIn,
        path: Annotated[str, Form()],
        description: Annotated[str, Form()] = "",
    ):
        return tag_change(request, pipe, describe_tag, "described", path, description)

    @router.post("/taxonomy/rename")
    def rename(
        request: Request,
        pipe: Pipe,
        _: LoggedIn,
        path: Annotated[str, Form()],
        new_path: Annotated[str, Form()],
    ):
        return tag_change(request, pipe, rename_tag, "renamed", path, new_path.strip())

    @router.post("/taxonomy/delete")
    def delete(request: Request, pipe: Pipe, _: LoggedIn, path: Annotated[str, Form()]):
        return tag_change(request, pipe, delete_tag, "deleted", path)

    @router.post("/taxonomy/retag")
    def retag(
        background: BackgroundTasks,
        pipe: Pipe,
        _: LoggedIn,
        every_item: Annotated[bool, Form(alias="all")] = False,
    ):
        item_ids = retag_targets(pipe.storage, every_item)
        background.add_task(pipe.retag_all, item_ids)
        return RedirectResponse(f"/ui/taxonomy?retagging={len(item_ids)}", status.HTTP_303_SEE_OTHER)

    def item_page(request: Request, pipe: Pipeline, item_id: str, status_code: int = status.HTTP_200_OK, **context):
        current = pipe.storage.get_item(item_id)
        versions = pipe.storage.list_versions(item_id)
        if current is None and not versions:
            return not_found(request, "item")
        pending = any(v.status is VersionStatus.PENDING for v in versions)
        tags = tag_paths(pipe)
        addable = [path for path in tags if current is None or path not in current.tags]
        return page(
            request,
            "item.html",
            status_code,
            item_id=item_id,
            item=current,
            shown=next((v for v in versions if current and v.id == current.current_version_id), None),
            versions=versions,
            pending=pending,
            poll=UI_PENDING_POLL,
            addable=sorted(addable, key=lambda path: path.split("/")),
            tags=tags,
            **context,
        )

    @router.get("/items/{item_id}")
    def item(request: Request, item_id: str, pipe: Pipe, _: LoggedIn):
        return item_page(request, pipe, item_id)

    def edit_tags(request: Request, pipe: Pipeline, item_id: str, edit, path: str):
        try:
            edited = edit(pipe.storage, item_id, path)
        except ValueError as exc:
            return item_page(request, pipe, item_id, status.HTTP_422_UNPROCESSABLE_CONTENT, error=str(exc))
        if edited is None:
            return not_found(request, "item")
        return RedirectResponse(f"/ui/items/{item_id}", status.HTTP_303_SEE_OTHER)

    @router.post("/items/{item_id}/tags")
    def add_owner_tag(request: Request, item_id: str, pipe: Pipe, _: LoggedIn, path: Annotated[str, Form()]):
        return edit_tags(request, pipe, item_id, tag_item, path)

    @router.post("/items/{item_id}/untag")
    def untag(request: Request, item_id: str, pipe: Pipe, _: LoggedIn, path: Annotated[str, Form()]):
        return edit_tags(request, pipe, item_id, untag_item, path)

    @router.post("/items/{item_id}/allow")
    def allow_again(request: Request, item_id: str, pipe: Pipe, _: LoggedIn, path: Annotated[str, Form()]):
        return edit_tags(request, pipe, item_id, allow_tag, path)

    @router.post("/items/{item_id}/notes")
    def edit_note(request: Request, item_id: str, pipe: Pipe, _: LoggedIn, notes: Annotated[str, Form()] = ""):
        if len(notes) > NOTE_MAX_CHARS:
            error = f"The note is too long ({len(notes):,} characters, at most {NOTE_MAX_CHARS:,})."
            return item_page(request, pipe, item_id, status.HTTP_422_UNPROCESSABLE_CONTENT, error=error, draft=notes)
        try:
            noted = write_note(pipe.storage, item_id, notes)
        except ValueError as exc:
            return item_page(request, pipe, item_id, status.HTTP_422_UNPROCESSABLE_CONTENT, error=str(exc))
        if noted is None:
            return not_found(request, "item")
        return RedirectResponse(f"/ui/items/{item_id}", status.HTTP_303_SEE_OTHER)

    @router.post("/items/{item_id}/thought")
    def edit_thought(
        request: Request,
        item_id: str,
        background: BackgroundTasks,
        pipe: Pipe,
        _: LoggedIn,
        text: Annotated[str, Form()] = "",
        title: Annotated[str, Form()] = "",
        tags: Annotated[list[str], Form()] = [],  # noqa: B006 - FastAPI copies form defaults
    ):
        draft = {"title": title, "text": text, "tags": tags}
        try:
            version = pipe.edit(item_id, ThoughtEdit(**draft))
        except ValueError as exc:
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
            return item_page(request, pipe, item_id, code, error=thought_error(exc), thought_draft=draft)
        if version is None:
            return not_found(request, "item")
        background.add_task(pipe.enrich, version)
        return RedirectResponse(f"/ui/items/{item_id}", status.HTTP_303_SEE_OTHER)

    @router.post("/items/{item_id}/retry")
    def retry_thought(request: Request, item_id: str, background: BackgroundTasks, pipe: Pipe, _: LoggedIn):
        try:
            version = pipe.retry(item_id)
        except ValueError as exc:
            return item_page(request, pipe, item_id, status.HTTP_409_CONFLICT, error=str(exc))
        if version is None:
            return not_found(request, "item")
        background.add_task(pipe.enrich, version)
        return RedirectResponse(f"/ui/items/{item_id}", status.HTTP_303_SEE_OTHER)

    @router.post("/items/{item_id}/delete")
    def delete_item(request: Request, item_id: str, pipe: Pipe, _: LoggedIn):
        if not pipe.storage.delete_item(item_id):
            return not_found(request, "item")
        return RedirectResponse("/ui", status.HTTP_303_SEE_OTHER)

    @router.get("/versions/{version_id}")
    def version(request: Request, version_id: str, pipe: Pipe, _: LoggedIn):
        v = pipe.storage.get_version(version_id)
        if v is None:
            return not_found(request, "version")
        return page(request, "_version.html", v=v)

    @router.post("/versions/{version_id}/delete")
    def remove_version(request: Request, version_id: str, pipe: Pipe, _: LoggedIn):
        v = pipe.storage.get_version(version_id)
        if v is None:
            return not_found(request, "version")
        try:
            delete_version(pipe.storage, version_id)
        except LastVersion as exc:
            return item_page(request, pipe, v.item_id, status.HTTP_409_CONFLICT, error=str(exc).capitalize() + ".")
        return RedirectResponse(f"/ui/items/{v.item_id}", status.HTTP_303_SEE_OTHER)

    return router


def date_filter(start: str, end: str) -> dict:
    """Context for the saved-date fields. An invalid range filters nothing and says why."""
    try:
        saved, error = DateRange(start=start or None, end=end or None), None
    except ValidationError as exc:
        saved, error = None, f"Dates ignored: {exc.errors()[0]['msg'].removeprefix('Value error, ')}."
    today = datetime.now(UTC).date()
    presets = {
        "Last 7 days": (str(today - timedelta(days=7)), str(today)),
        "Last 30 days": (str(today - timedelta(days=30)), str(today)),
        "All dates": ("", ""),
    }
    return {"saved": saved, "dates": {"from": start, "to": end}, "date_error": error, "date_presets": presets}


def kind_filter(kind: str) -> dict:
    """Context for the Kind selector; an unknown Kind filters nothing."""
    return {"kind": Kind(kind) if kind in Kind else None, "kinds": list(Kind)}


def thought_error(exc: ValueError) -> str:
    if isinstance(exc, ValidationError):
        error = exc.errors()[0]
        return f"{str(error['loc'][-1]).capitalize()}: {error['msg'].removeprefix('Value error, ')}."
    return f"{str(exc).capitalize()}."


def keep_filters(url: str, request: Request) -> str:
    """`url` with the current page's saved-date range and Kind, so the filters carry over between views."""
    kept = {k: request.query_params[k] for k in ("from", "to", "kind") if request.query_params.get(k)}
    if not kept:
        return url
    return f"{url}{'&' if '?' in url else '?'}{urlencode(kept)}"


class TagNode(NamedTuple):
    tag: Tag
    children: list["TagNode"]


def tag_tree(tags: list[Tag]) -> list[TagNode]:
    """Root nodes, children in path order."""
    nodes = {t.path: TagNode(t, []) for t in sorted(tags, key=lambda t: t.path.split("/"))}
    roots = []
    for node in nodes.values():
        siblings = nodes[node.tag.parent].children if node.tag.parent in nodes else roots
        siblings.append(node)
    return roots


def safe_next(next_url: str) -> str:
    """Only redirect back into the UI after login, never to another site."""
    return next_url if next_url.startswith("/ui") else "/ui"
