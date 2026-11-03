"""Domain models: what a Capture is asked for, the Version and Item it produces, and the Taxonomy."""

import hashlib
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from kb.config import (
    NOTE_MAX_CHARS,
    SESSION_PIPELINE_MAX_CHARS,
    SESSION_TITLE_MAX_CHARS,
    THOUGHT_DERIVED_TITLE_CHARS,
    THOUGHT_MAX_CHARS,
    THOUGHT_PIPELINE_MAX_CHARS,
    THOUGHT_TITLE_MAX_CHARS,
)
from kb.normalize import item_id, normalise_url, version_id


class Channel(StrEnum):
    EXTENSION = "extension"
    RSS = "rss"
    MANUAL = "manual"
    RETAG = "retag"
    WRITTEN = "written"
    MCP = "mcp"  # a Thought written by an agent for the Owner
    SESSION = "session"  # a Session Summary imported from its Summary File


class Kind(StrEnum):
    ARTICLE = "article"
    THOUGHT = "thought"
    SESSION = "session"


class VersionStatus(StrEnum):
    PENDING = "pending"
    ENRICHED = "enriched"
    FAILED = "failed"


class CaptureRequest(BaseModel):
    """Body of POST /capture. `content` is the browser-rendered HTML; absent means the server fetches.
    `tags` are picked by the Owner; when given, the pipeline does not tag this Capture.
    `note` is added below the Item's Note; the pipeline never sees it."""

    url: str
    content: str | None = None
    captured_at: datetime | None = None
    channel: Channel
    tags: list[str] = Field(default_factory=list)
    note: str = Field("", max_length=NOTE_MAX_CHARS)

    @field_validator("channel")
    @classmethod
    def _captured(cls, channel: Channel) -> Channel:
        if channel is Channel.RETAG:
            raise ValueError("retag Versions are created by the re-tag action, not captured")
        if channel in (Channel.WRITTEN, Channel.MCP):
            raise ValueError("Thoughts are written, not captured")
        if channel is Channel.SESSION:
            raise ValueError("Session Summaries are imported, not captured")
        return channel


class ThoughtEdit(BaseModel):
    """Body of PUT /thoughts/{id}. `tags` picked by the Owner skip the pipeline's tagging, as for a Capture."""

    title: str = Field("", max_length=THOUGHT_TITLE_MAX_CHARS)
    text: str = Field(max_length=THOUGHT_MAX_CHARS)
    tags: list[str] = Field(default_factory=list)

    @field_validator("title", "text")
    @classmethod
    def _stripped(cls, value: str) -> str:
        return value.replace("\r\n", "\n").strip()

    @field_validator("text")
    @classmethod
    def _not_empty(cls, text: str) -> str:
        if not text:
            raise ValueError("a Thought needs some text")
        return text


class ThoughtRequest(ThoughtEdit):
    """Body of POST /thoughts. Sending the same `written_at` again returns the Thought already written."""

    written_at: datetime | None = None


class Agent(StrEnum):
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"


class SessionStatus(StrEnum):
    DONE = "done"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    ABANDONED = "abandoned"


class Decision(BaseModel):
    decision: str
    reason: str = ""
    rejected: str = ""  # the alternative that was not taken

    def line(self) -> str:
        parts = [
            self.decision,
            f"Reason: {self.reason}" if self.reason else "",
            f"Rejected: {self.rejected}" if self.rejected else "",
        ]
        return "- " + " ".join(p for p in parts if p)


class Problem(BaseModel):
    symptom: str
    cause: str = ""
    fix: str = ""

    def line(self) -> str:
        parts = [self.symptom, f"Cause: {self.cause}" if self.cause else "", f"Fix: {self.fix}" if self.fix else ""]
        return "- " + " ".join(p for p in parts if p)


class SessionSummary(BaseModel):
    """What the agent writes about a Session (D43). Empty sections are left out, so a small Session stays short."""

    title: str = Field(min_length=1, max_length=SESSION_TITLE_MAX_CHARS)
    status: SessionStatus
    goal: str = ""
    outcome: str = ""
    decisions: list[Decision] = Field(default_factory=list)
    problems: list[Problem] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)
    todo: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    def text(self) -> str:
        """The sections as the Item's text, each present one under its heading; this is what search and
        the embedding read."""
        blocks = [
            f"Goal: {self.goal}" if self.goal else "",
            f"Outcome: {self.outcome}" if self.outcome else "",
            _section("Decisions", [d.line() for d in self.decisions]),
            _section("Problems", [p.line() for p in self.problems]),
            _section("Dropped", [f"- {d}" for d in self.dropped]),
            _section("Todo", [f"- {t}" for t in self.todo]),
            _section("Sources", [f"- {s}" for s in self.sources]),
            f"Keywords: {', '.join(self.keywords)}" if self.keywords else "",
        ]
        return "\n\n".join(b for b in blocks if b)


def _section(heading: str, lines: list[str]) -> str:
    return f"{heading}:\n" + "\n".join(lines) if lines else ""


class SessionMeta(BaseModel):
    """What code reads from the Transcript (D43); the agent never writes these."""

    agent: Agent
    session_id: str = Field(min_length=1)
    client: str = ""  # the agent's own name for where it ran, e.g. Claude Code's entrypoint
    folder: str = ""
    branch: str = ""
    repo_url: str = ""
    transcript_path: str = ""
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ModelUsage(BaseModel):
    """Tokens one model used in a Session. Input excludes cache reads; thinking is part of the output."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class SessionUsage(BaseModel):
    models: list[ModelUsage] = Field(default_factory=list)
    owner_turns: int = 0
    tool_calls: int = 0
    cost_usd: float | None = None  # only where the agent reports it; no price table of our own


class SessionRecord(BaseModel):
    """A Session Summary as its Version keeps it, read-only (D42, D43)."""

    meta: SessionMeta
    usage: SessionUsage = Field(default_factory=SessionUsage)
    summary: SessionSummary
    # Written later from the Transcript, by an agent that was not in the Session.
    after_the_fact: bool = False


class Enrichment(BaseModel):
    """Everything the pipeline derives from a Version's content, plus how it was produced."""

    # Empty for a Thought: its title and text are the Owner's, on the Version; it is never summarised.
    title: str = ""
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    published_date: date | None = None
    language: str | None = None
    tags: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None

    model: str | None = None
    prompt_version: str | None = None
    taxonomy_version: int
    embedding_model: str
    tag_model: str | None = None
    tag_prompt_version: str | None = None
    # The Version whose summary and embedding this is, when they were not computed for this one.
    reused_from: str | None = None


class Version(BaseModel):
    """One Capture of an Item, or one writing of a Thought. Immutable once enriched; `content` is kept only
    while pending, a Thought's `title` and `text` always."""

    id: str
    item_id: str
    captured_at: datetime
    channel: Channel
    kind: Kind = Kind.ARTICLE
    original_url: str | None = None
    title: str = ""
    text: str | None = None
    content_hash: str
    content: str | None = None
    status: VersionStatus = VersionStatus.PENDING
    enrichment: Enrichment | None = None
    error: str | None = None
    # Tags the Owner picked with this Capture; they go to the Item's owner tags.
    owner_tags: list[str] = Field(default_factory=list)
    # The Note written with this Capture; it goes below the Item's Note.
    note: str = ""
    # A session Version's Session Summary and what its Transcript says; no other kind has one.
    session: SessionRecord | None = None

    @model_validator(mode="after")
    def _session_record(self) -> "Version":
        if (self.kind is Kind.SESSION) != (self.session is not None):
            raise ValueError("a session Version has a session record, and only a session Version has one")
        return self

    @classmethod
    def create(cls, request: CaptureRequest, captured_at: datetime, content: str) -> "Version":
        iid = item_id(normalise_url(request.url))
        return cls(
            id=version_id(iid, captured_at),
            item_id=iid,
            captured_at=captured_at,
            channel=request.channel,
            original_url=request.url,
            content_hash=content_hash(content),
            content=content,
            owner_tags=sorted(set(request.tags)),
            note=request.note.strip(),
        )

    @classmethod
    def written(cls, item_id: str, at: datetime, thought: ThoughtEdit, channel: Channel = Channel.WRITTEN) -> "Version":
        return cls(
            id=version_id(item_id, at),
            item_id=item_id,
            captured_at=at,
            channel=channel,
            kind=Kind.THOUGHT,
            title=thought.title,
            text=thought.text,
            content_hash=content_hash(thought.text),
            owner_tags=sorted(set(thought.tags)),
        )

    @classmethod
    def session_summary(cls, item_id: str, at: datetime, record: SessionRecord, owner_tags: list[str]) -> "Version":
        return cls(
            id=version_id(item_id, at),
            item_id=item_id,
            captured_at=at,
            channel=Channel.SESSION,
            kind=Kind.SESSION,
            content_hash=content_hash(record.summary.text()),
            owner_tags=sorted(set(owner_tags)),
            session=record,
        )

    def pipeline_input(self, enrichment: Enrichment | None = None) -> tuple[str, str]:
        """The title and text the pipeline reads: a Thought's own, an article's summary and key points, a
        Session Summary's own."""
        if self.kind is Kind.SESSION:
            return self.session.summary.title, self.session.summary.text()[:SESSION_PIPELINE_MAX_CHARS]
        if self.kind is Kind.THOUGHT:
            return thought_title(self.title, self.text), self.text[:THOUGHT_PIPELINE_MAX_CHARS]
        e = enrichment
        return e.title, "\n".join([e.summary, "", *(f"- {p}" for p in e.key_points)])

    def enriched(self, enrichment: Enrichment) -> "Version":
        return self.model_copy(update={"enrichment": enrichment, "status": VersionStatus.ENRICHED, "content": None})

    def failed(self, error: str) -> "Version":
        return self.model_copy(update={"error": error, "status": VersionStatus.FAILED})

    def retagged(self, at: datetime, enrichment: Enrichment) -> "Version":
        """A new Version of the same content with new tags."""
        return self.model_copy(
            update={
                "id": version_id(self.item_id, at),
                "captured_at": at,
                "channel": Channel.RETAG,
                "enrichment": enrichment,
                "owner_tags": [],
                "note": "",
            }
        )


class Annotations(BaseModel):
    """The Owner's corrections; they survive every new Capture and re-tag."""

    notes: str = ""
    owner_tags: list[str] = Field(default_factory=list)
    rejected_tags: list[str] = Field(default_factory=list)

    def noting(self, note: str) -> "Annotations":
        """The Note with `note` added below it."""
        if not note:
            return self
        return self.model_copy(update={"notes": f"{self.notes}\n\n{note}" if self.notes else note})

    def adding(self, tags: list[str]) -> "Annotations":
        return self.model_copy(
            update={
                "owner_tags": sorted(set(self.owner_tags) | set(tags)),
                "rejected_tags": sorted(set(self.rejected_tags) - set(tags)),
            }
        )

    def rejecting(self, tag: str) -> "Annotations":
        return self.model_copy(
            update={
                "owner_tags": sorted(set(self.owner_tags) - {tag}),
                "rejected_tags": sorted(set(self.rejected_tags) | {tag}),
            }
        )

    def allowing(self, tag: str) -> "Annotations":
        return self.model_copy(update={"rejected_tags": sorted(set(self.rejected_tags) - {tag})})

    def tags(self, pipeline_tags: list[str]) -> list[str]:
        """The Item's tags: the pipeline's plus the Owner's, minus the rejected ones."""
        return sorted((set(pipeline_tags) | set(self.owner_tags)) - set(self.rejected_tags))


class ItemView(BaseModel):
    """An Item as API clients see it: everything but the embedding, which only search uses."""

    id: str
    normalised_url: str | None = None
    original_url: str | None = None
    media_type: Kind = Kind.ARTICLE
    first_captured_at: datetime
    captured_at: datetime
    current_version_id: str
    title: str
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    text: str | None = None
    tags: list[str] = Field(default_factory=list)
    taxonomy_version: int = 0
    annotations: Annotations = Field(default_factory=Annotations)


class Item(ItemView):
    """Current view of one Item plus owner annotations: an article's newest enriched Version, a Thought's
    newest Version with the tags and embedding of its newest enriched one."""

    embedding: list[float] | None = None

    @classmethod
    def from_version(cls, version: Version, previous: "Item | None" = None) -> "Item":
        """An article's view once `version` is enriched; the Note and tags picked with it join the Annotations."""
        if version.enrichment is None:
            raise ValueError("only an enriched Version can become the current Item")
        annotations = (previous.annotations if previous else Annotations()).adding(version.owner_tags)
        annotations = annotations.noting(version.note)
        return cls._article(version, annotations, previous.first_captured_at if previous else version.captured_at)

    @classmethod
    def rebuilt(cls, versions: list[Version], annotations: Annotations, first_captured_at: datetime) -> "Item | None":
        """The view of an Item's Versions (newest first), or None when they have nothing to show yet."""
        enriched = next((v for v in versions if v.status is VersionStatus.ENRICHED), None)
        if versions and versions[0].kind is not Kind.ARTICLE:
            return cls._shown(versions[0], enriched, annotations, first_captured_at)
        return cls._article(enriched, annotations, first_captured_at) if enriched else None

    @classmethod
    def _article(cls, version: Version, annotations: Annotations, first_captured_at: datetime) -> "Item":
        e = version.enrichment
        return cls(
            id=version.item_id,
            normalised_url=normalise_url(version.original_url),
            original_url=version.original_url,
            first_captured_at=first_captured_at,
            captured_at=version.captured_at,
            current_version_id=version.id,
            title=e.title,
            summary=e.summary,
            key_points=e.key_points,
            tags=annotations.tags(e.tags),
            taxonomy_version=e.taxonomy_version,
            embedding=e.embedding,
            annotations=annotations,
        )

    @classmethod
    def _shown(
        cls, current: Version, enriched: Version | None, annotations: Annotations, first_captured_at: datetime
    ) -> "Item":
        """A Thought or a Session, shown as its newest Version reads whatever that Version's status; tags and
        embedding come from the newest enriched Version."""
        e = enriched.enrichment if enriched else None
        if current.kind is Kind.SESSION:
            title, text = current.session.summary.title, current.session.summary.text()
        else:
            title, text = thought_title(current.title, current.text), current.text
        return cls(
            id=current.item_id,
            media_type=current.kind,
            first_captured_at=first_captured_at,
            captured_at=current.captured_at,
            current_version_id=current.id,
            title=title,
            text=text,
            tags=annotations.tags(e.tags if e else []),
            taxonomy_version=e.taxonomy_version if e else 0,
            embedding=e.embedding if e else None,
            annotations=annotations,
        )

    def annotated(self, annotations: Annotations, pipeline_tags: list[str]) -> "Item":
        return self.model_copy(update={"annotations": annotations, "tags": annotations.tags(pipeline_tags)})


class Match(ItemView):
    """An Item a search found, with its score relative to the other results of that search."""

    score: float


class Tag(BaseModel):
    """A node of the Taxonomy, e.g. `ai/retrieval/rag`. Never changed once created."""

    path: str
    description: str = ""
    created_at: datetime
    created_in_taxonomy_version: int

    @property
    def parent(self) -> str | None:
        return self.path.rpartition("/")[0] or None

    @property
    def name(self) -> str:
        return self.path.rpartition("/")[2]


class Taxonomy(BaseModel):
    """Snapshot of all Tags; its version is that of the newest Tag, 0 when empty."""

    tags: list[Tag] = Field(default_factory=list)

    @computed_field
    @property
    def version(self) -> int:
        return max((t.created_in_taxonomy_version for t in self.tags), default=0)

    def get(self, path: str) -> Tag | None:
        return next((t for t in self.tags if t.path == path), None)


class DateRange(BaseModel):
    """Whole UTC days, both ends inclusive; a missing end is open."""

    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> "DateRange":
        if self.start and self.end and self.start > self.end:
            raise ValueError("the start date is after the end date")
        return self

    @property
    def lower(self) -> datetime | None:
        return datetime.combine(self.start, time(), UTC) if self.start else None

    @property
    def upper(self) -> datetime | None:
        """Exclusive: midnight after the end day."""
        return datetime.combine(self.end + timedelta(days=1), time(), UTC) if self.end else None

    def contains(self, at: datetime) -> bool:
        return (self.lower is None or at >= self.lower) and (self.upper is None or at < self.upper)


def thought_title(title: str, text: str) -> str:
    """The Owner's title, or else the first line of the text."""
    if title:
        return title
    first = text.strip().split("\n", 1)[0].strip()
    if len(first) <= THOUGHT_DERIVED_TITLE_CHARS:
        return first
    return first[: THOUGHT_DERIVED_TITLE_CHARS - 1].rstrip() + "…"


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
