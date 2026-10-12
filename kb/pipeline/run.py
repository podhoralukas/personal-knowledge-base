"""Capture, enrichment and re-tag orchestration."""

import logging
from datetime import UTC, datetime, timedelta

from kb.llm import LLM
from kb.models import (
    Annotations,
    CaptureRequest,
    Channel,
    Enrichment,
    Item,
    Kind,
    Taxonomy,
    ThoughtEdit,
    ThoughtRequest,
    Version,
    VersionStatus,
)
from kb.normalize import normalise_url, thought_id, version_id
from kb.pipeline.fetch import fetch, html_to_markdown
from kb.pipeline.summarise import PROMPT_VERSION, summarise
from kb.pipeline.tag import PROMPT_VERSION as TAG_PROMPT_VERSION
from kb.pipeline.tag import merge, tag
from kb.storage import Storage

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, storage: Storage, llm: LLM) -> None:
        self.storage = storage
        self.llm = llm

    async def capture(self, request: CaptureRequest) -> Version:
        """Get the content (from the browser or by fetching), store a pending Version, return it."""
        normalise_url(request.url)  # reject a malformed URL before fetching it
        self._known(request.tags)
        if request.content is not None:
            markdown = await html_to_markdown(request.content, base_url=request.url)
        else:
            fetched = await fetch(request.url)
            markdown = fetched.markdown
            request = request.model_copy(update={"url": fetched.url})

        version = Version.create(request, request.captured_at or datetime.now(UTC), markdown)
        self.storage.put_version(version)
        return version

    def write(self, thought: ThoughtRequest, channel: Channel = Channel.WRITTEN) -> Version:
        """Store a new Thought, shown at once; enrichment follows. The same `written_at` returns the stored one."""
        self._known(thought.tags)
        at = thought.written_at or datetime.now(UTC)
        iid = thought_id(at)
        existing = self.storage.get_version(version_id(iid, at))
        if existing is not None:
            return existing
        version = Version.written(iid, at, thought, channel)
        self._show(version, Annotations().adding(version.owner_tags), at)
        return version

    def edit(self, item_id: str, thought: ThoughtEdit) -> Version | None:
        """A new Version of the Thought, shown at once; None for an unknown Item."""
        item = self.storage.get_item(item_id)
        if item is None:
            return None
        if item.media_type is not Kind.THOUGHT:
            raise ValueError("only a Thought can be edited")
        self._known(thought.tags)
        at = max(
            datetime.now(UTC), item.captured_at + timedelta(milliseconds=1)
        )  # newest even after a future written_at
        version = Version.written(item_id, at, thought)
        self._show(version, item.annotations.adding(version.owner_tags), item.first_captured_at)
        return version

    def retry(self, item_id: str) -> Version | None:
        """Make a Thought's failed current Version pending again; None for an unknown Item."""
        item = self.storage.get_item(item_id)
        if item is None:
            return None
        current = self.storage.get_version(item.current_version_id)
        if current.status is not VersionStatus.FAILED:
            raise ValueError("nothing to retry: the current version did not fail")
        pending = current.model_copy(update={"status": VersionStatus.PENDING, "error": None})
        self.storage.put_version(pending)
        return pending

    async def enrich(self, version: Version) -> Version:
        """Complete a pending Version and update the Item's current view. Failures are recorded, not raised."""
        try:
            enrichment = await self._enrichment(version)
        except Exception as exc:
            log.exception("enrichment failed for %s", version.id)
            failed = version.failed(repr(exc))
            if not self._deleted_meanwhile(version.id):
                self.storage.put_version(failed)
            return failed

        enriched = version.enriched(enrichment)
        if not self._deleted_meanwhile(version.id):
            self._store(enriched)
        return enriched

    async def retag(self, item_id: str) -> Version | None:
        """Tag the Item's current Version against the current Taxonomy and store that as a new Version."""
        item = self.storage.get_item(item_id)
        if item is None:
            return None
        current = self.storage.get_version(item.current_version_id)
        if current.status is not VersionStatus.ENRICHED:
            return None  # a Thought's edit still pending or failed
        taxonomy = self.storage.get_taxonomy()
        suggested = await self._tagged(current, self._reused(current), taxonomy, item.annotations.rejected_tags)
        enrichment = suggested.model_copy(update={"tags": merge(current.enrichment.tags, suggested.tags)})
        retagged = current.retagged(datetime.now(UTC), enrichment)
        if self._deleted_meanwhile(current.id):
            return None
        self._store(retagged)
        return retagged

    async def retag_all(self, item_ids: list[str]) -> None:
        """Failures are logged and skipped."""
        for item_id in item_ids:
            try:
                await self.retag(item_id)
            except Exception:
                log.exception("re-tag failed for %s", item_id)

    def _deleted_meanwhile(self, version_id: str) -> bool:
        """Storing a result for a Version deleted during the LLM calls would bring its Item back."""
        if self.storage.get_version(version_id) is not None:
            return False
        log.info("%s was deleted while being processed; result dropped", version_id)
        return True

    def _known(self, tags: list[str]) -> None:
        unknown = set(tags) - {t.path for t in self.storage.get_taxonomy().tags}
        if unknown:
            raise ValueError(f"tags not in the taxonomy: {', '.join(sorted(unknown))}")

    def _store(self, version: Version) -> None:
        previous = self.storage.get_item(version.item_id)
        if version.kind is Kind.THOUGHT:
            if previous is not None:
                self._show(version, previous.annotations, previous.first_captured_at)
            return
        self.storage.put_version(version)
        self.storage.put_item(Item.from_version(version, previous=previous))

    def _show(self, version: Version, annotations: Annotations, first_captured_at: datetime) -> None:
        """Store a Thought's Version and rebuild its Item, which shows the newest text whatever its status."""
        self.storage.put_version(version)
        versions = self.storage.list_versions(version.item_id)
        self.storage.put_item(Item.rebuilt(versions, annotations, first_captured_at))

    async def _enrichment(self, version: Version) -> Enrichment:
        taxonomy = self.storage.get_taxonomy()
        previous = self._same_input(version)
        summarised = await self._summarised(version) if previous is None else self._reused(previous)
        if version.owner_tags:
            return self._tagged_by_owner(summarised, taxonomy)

        same_tagging = (summarised.taxonomy_version, summarised.tag_prompt_version, summarised.tag_model) == (
            taxonomy.version,
            TAG_PROMPT_VERSION,
            self.llm.model,
        )
        if previous is not None and same_tagging:
            return summarised
        item = self.storage.get_item(version.item_id)
        rejected = item.annotations.rejected_tags if item else []
        return await self._tagged(version, summarised, taxonomy, rejected)

    def _same_input(self, version: Version) -> Version | None:
        """The previous Version, if it has the same content summarised (a Thought: embedded) the same way."""
        summarised_by = (self.llm.model, PROMPT_VERSION) if version.kind is Kind.ARTICLE else (None, None)
        for previous in self.storage.list_versions(version.item_id):
            if previous.id == version.id or previous.status is not VersionStatus.ENRICHED:
                continue
            e = previous.enrichment
            same_inputs = (e.model, e.prompt_version, e.embedding_model) == (*summarised_by, self.llm.embedding_model)
            return previous if previous.content_hash == version.content_hash and same_inputs else None
        return None

    @staticmethod
    def _reused(version: Version) -> Enrichment:
        e = version.enrichment
        return e.model_copy(update={"reused_from": e.reused_from or version.id})

    async def _summarised(self, version: Version) -> Enrichment:
        """Summary and embedding only, a Thought's embedding only; tags are filled in by `_tagged`."""
        if version.kind is Kind.THOUGHT:
            embedding = await self.llm.embed("\n".join(version.pipeline_input()))
            return Enrichment(embedding=embedding, taxonomy_version=0, embedding_model=self.llm.embedding_model)
        if version.content is None:
            raise ValueError("pending Version has no content")
        summary = await summarise(self.llm, version.content)
        embedding = await self.llm.embed(f"{summary.title}\n{summary.summary}")
        return Enrichment(
            **summary.model_dump(),
            embedding=embedding,
            model=self.llm.model,
            prompt_version=PROMPT_VERSION,
            taxonomy_version=0,
            embedding_model=self.llm.embedding_model,
        )

    async def _tagged(
        self, version: Version, enrichment: Enrichment, taxonomy: Taxonomy, rejected: list[str]
    ) -> Enrichment:
        """Tags chosen from scratch; the LLM is not offered the Item's rejected Tags."""
        offered = Taxonomy(tags=[t for t in taxonomy.tags if t.path not in rejected])
        tags = await tag(self.llm, offered, *version.pipeline_input(enrichment))
        return enrichment.model_copy(
            update={
                "tags": tags,
                "taxonomy_version": taxonomy.version,
                "tag_model": self.llm.model,
                "tag_prompt_version": TAG_PROMPT_VERSION,
            }
        )

    @staticmethod
    def _tagged_by_owner(enrichment: Enrichment, taxonomy: Taxonomy) -> Enrichment:
        """No tag step: the Owner picked the tags, which reach the Item as owner tags."""
        update = {"tags": [], "taxonomy_version": taxonomy.version, "tag_model": None, "tag_prompt_version": None}
        return enrichment.model_copy(update=update)
