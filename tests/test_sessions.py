from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kb.llm.fake import FakeLLM
from kb.models import (
    Agent,
    Annotations,
    CaptureRequest,
    Channel,
    Decision,
    Item,
    Kind,
    Problem,
    SessionMeta,
    SessionRecord,
    SessionStatus,
    SessionSummary,
    ThoughtEdit,
    ThoughtRequest,
    Version,
    VersionStatus,
)
from kb.normalize import session_item_id, thought_id
from kb.notes import write_note
from kb.pipeline.run import Pipeline
from kb.pipeline.tag import Tagging
from kb.storage.memory import MemoryStorage
from kb.taxonomy import add_tag, retag_candidates, retag_targets
from kb.versions import SessionReadOnly, delete_version

T1 = datetime(2026, 11, 2, 9, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 3, 9, 0, 0, tzinfo=UTC)


def summary(**overrides) -> SessionSummary:
    fields = dict(
        title="Fix the index",
        status=SessionStatus.DONE,
        goal="Make search find Threads.",
        outcome="Search finds them.",
        decisions=[Decision(decision="Pin OpenSearch 3.9.0", reason="3.4 closes readers early", rejected="Keep 3.4")],
        problems=[Problem(symptom="503 already_closed on .vec", cause="k-NN 3.4 bug", fix="pin 3.9.0")],
        keywords=["already_closed_exception"],
    )
    return SessionSummary(**(fields | overrides))


def record(summary_overrides: dict | None = None, agent=Agent.CLAUDE_CODE, session_id="8f2c") -> SessionRecord:
    return SessionRecord(
        meta=SessionMeta(agent=agent, session_id=session_id, folder="/work/kb", model="claude-opus"),
        summary=summary(**(summary_overrides or {})),
    )


class FailingLLM(FakeLLM):
    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding service down")


@pytest.fixture
def storage():
    s = MemoryStorage()
    add_tag(s, "project")
    add_tag(s, "project/kb")
    return s


class TestSummary:
    def test_empty_sections_are_left_out(self):
        short = SessionSummary(title="Short", status=SessionStatus.DONE, goal="Check the link.")
        assert short.text() == "Goal: Check the link."

    def test_every_section_is_rendered_with_its_reasons(self):
        assert summary().text() == (
            "Goal: Make search find Threads.\n\n"
            "Outcome: Search finds them.\n\n"
            "Decisions:\n- Pin OpenSearch 3.9.0 Reason: 3.4 closes readers early Rejected: Keep 3.4\n\n"
            "Problems:\n- 503 already_closed on .vec Cause: k-NN 3.4 bug Fix: pin 3.9.0\n\n"
            "Keywords: already_closed_exception"
        )

    def test_a_title_is_required(self):
        with pytest.raises(ValidationError):
            summary(title="")

    def test_a_status_is_required(self):
        with pytest.raises(ValidationError):
            SessionSummary(title="T", status="finished")


class TestIdentity:
    def test_the_item_id_is_the_agent_and_its_session_id(self):
        assert session_item_id(Agent.CLAUDE_CODE, "8f2c") == session_item_id("claude-code", "8f2c")

    def test_the_same_session_id_in_two_agents_is_two_sessions(self):
        assert session_item_id(Agent.CLAUDE_CODE, "8f2c") != session_item_id(Agent.CODEX, "8f2c")

    def test_a_session_is_not_a_thought(self):
        assert session_item_id(Agent.CODEX, "8f2c") != thought_id(T1)


class TestVersion:
    def test_a_session_version_keeps_its_record_and_hashes_its_text(self):
        v = Version.session_summary(session_item_id(Agent.CLAUDE_CODE, "8f2c"), T1, record(), ["project/kb"])
        assert (v.kind, v.channel, v.status, v.owner_tags) == (
            Kind.SESSION,
            Channel.SESSION,
            VersionStatus.PENDING,
            ["project/kb"],
        )
        assert v.session.summary.title == "Fix the index"
        assert v.text is None and v.content is None

    def test_a_session_version_needs_its_record(self):
        with pytest.raises(ValidationError, match="session record"):
            Version(id="x", item_id="y", captured_at=T1, channel=Channel.SESSION, kind=Kind.SESSION, content_hash="h")

    def test_only_a_session_version_has_a_record(self):
        with pytest.raises(ValidationError, match="session record"):
            Version(id="x", item_id="y", captured_at=T1, channel=Channel.MANUAL, content_hash="h", session=record())

    def test_a_session_is_not_captured(self):
        with pytest.raises(ValidationError, match="saved by an agent, not captured"):
            CaptureRequest(url="https://example.com", channel=Channel.SESSION)

    def test_a_pending_session_already_shows_as_an_item(self):
        v = Version.session_summary(session_item_id(Agent.CLAUDE_CODE, "8f2c"), T1, record(), [])
        item = Item.rebuilt([v], Annotations(), T1)
        assert (item.media_type, item.title, item.text, item.tags) == (
            Kind.SESSION,
            "Fix the index",
            summary().text(),
            [],
        )
        assert item.embedding is None


class TestPipeline:
    def test_a_session_is_shown_at_once(self, storage):
        v = Pipeline(storage, FakeLLM()).session(record(), T1)
        item = storage.get_item(v.item_id)
        assert (item.media_type, item.title, item.text) == (Kind.SESSION, "Fix the index", summary().text())
        assert storage.get_version(v.id) == v

    async def test_enrichment_embeds_the_summary_and_nothing_else(self, storage):
        llm = FakeLLM()  # no answers: a summarise or tag call would fail
        pipeline = Pipeline(storage, llm)
        v = pipeline.session(record(), T1)
        enriched = await pipeline.enrich(v)

        assert enriched.status is VersionStatus.ENRICHED
        assert (enriched.enrichment.tags, enriched.enrichment.summary) == ([], "")
        assert enriched.enrichment.embedding is not None
        assert llm.calls == []
        assert llm.embedded == [f"Fix the index\n{summary().text()}"]

    async def test_a_failed_embedding_leaves_the_session_shown(self, storage):
        pipeline = Pipeline(storage, FailingLLM())
        v = pipeline.session(record(), T1)
        failed = await pipeline.enrich(v)
        item = storage.get_item(v.item_id)
        assert failed.status is VersionStatus.FAILED
        assert (item.title, item.text, item.embedding) == ("Fix the index", summary().text(), None)

    def test_the_project_tag_is_an_owner_tag(self, storage):
        v = Pipeline(storage, FakeLLM()).session(record(), T1, tags=["project/kb"])
        item = storage.get_item(v.item_id)
        assert (item.tags, item.annotations.owner_tags) == (["project/kb"], ["project/kb"])

    def test_an_unknown_tag_is_refused(self, storage):
        with pytest.raises(ValueError, match="not in the taxonomy"):
            Pipeline(storage, FakeLLM()).session(record(), T1, tags=["project/nope"])

    def test_the_same_session_at_the_same_instant_is_stored_once(self, storage):
        pipeline = Pipeline(storage, FakeLLM())
        first = pipeline.session(record(), T1)
        assert pipeline.session(record(), T1) == first
        assert len(storage.list_versions(first.item_id)) == 1

    async def test_a_new_summary_adds_a_version_and_keeps_the_owners_annotations(self, storage):
        pipeline = Pipeline(storage, FakeLLM())
        first = pipeline.session(record(), T1, tags=["project/kb"])
        await pipeline.enrich(first)
        write_note(storage, first.item_id, "Remember the pin")

        second = pipeline.session(record({"outcome": "Later"}), T2)
        item = storage.get_item(first.item_id)

        assert item.current_version_id == second.id
        assert item.text == summary(outcome="Later").text()
        assert (item.annotations.notes, item.annotations.owner_tags) == ("Remember the pin", ["project/kb"])
        assert item.first_captured_at == T1
        assert len(storage.list_versions(first.item_id)) == 2

    def test_summaries_imported_out_of_order_give_the_same_item(self, storage):
        pipeline = Pipeline(storage, FakeLLM())
        newer = pipeline.session(record({"outcome": "Later"}), T2)
        pipeline.session(record(), T1)
        item = storage.get_item(newer.item_id)
        assert (item.current_version_id, item.first_captured_at) == (newer.id, T1)

    def test_a_session_summary_cannot_be_edited(self, storage):
        v = Pipeline(storage, FakeLLM()).session(record(), T1)
        with pytest.raises(ValueError, match="cannot be edited"):
            Pipeline(storage, FakeLLM()).edit(v.item_id, ThoughtEdit(text="Changed"))
        assert storage.get_item(v.item_id).text == summary().text()

    async def test_a_session_is_never_retagged(self, storage):
        pipeline = Pipeline(storage, FakeLLM())
        v = await pipeline.enrich(pipeline.session(record(), T1))
        add_tag(storage, "ai")
        assert await pipeline.retag(v.item_id) is None
        assert len(storage.list_versions(v.item_id)) == 1

    def test_a_session_is_not_a_retag_target_after_a_new_tag(self, storage):
        v = Pipeline(storage, FakeLLM()).session(record(), T1)
        add_tag(storage, "ai")
        assert [i.id for i in storage.list_items_tagged_before(storage.get_taxonomy().version)] == [v.item_id]
        assert retag_targets(storage) == []

    def test_a_session_is_not_reached_by_re_tagging_every_item(self, storage):
        Pipeline(storage, FakeLLM()).session(record(), T1)
        assert retag_targets(storage, every_item=True) == []

    def test_the_item_keeps_decisions_and_problems_line_by_line(self, storage):
        v = Pipeline(storage, FakeLLM()).session(record(), T1)
        item = storage.get_item(v.item_id)
        assert item.decisions == ["Pin OpenSearch 3.9.0 Reason: 3.4 closes readers early Rejected: Keep 3.4"]
        assert item.problems == ["503 already_closed on .vec Cause: k-NN 3.4 bug Fix: pin 3.9.0"]

    async def test_a_failed_embedding_can_be_retried(self, storage):
        v = await Pipeline(storage, FailingLLM()).enrich(Pipeline(storage, FailingLLM()).session(record(), T1))
        assert v.status is VersionStatus.FAILED
        pipeline = Pipeline(storage, FakeLLM())
        retried = await pipeline.enrich(pipeline.retry(v.item_id))
        assert retried.status is VersionStatus.ENRICHED
        assert storage.get_item(v.item_id).embedding is not None

    def test_a_session_version_cannot_be_deleted(self, storage):
        v = Pipeline(storage, FakeLLM()).session(record(), T1)
        with pytest.raises(SessionReadOnly, match="read-only"):
            delete_version(storage, v.id)
        assert storage.get_version(v.id) is not None

    def test_a_session_keeps_its_note(self, storage):
        v = Pipeline(storage, FakeLLM()).session(record(), T1)
        item = write_note(storage, v.item_id, "Remember the pin")
        assert (item.annotations.notes, item.text) == ("Remember the pin", summary().text())


class TestProjectsAndTheTagger:
    async def test_the_tagger_is_not_offered_projects(self, storage):
        add_tag(storage, "ai")
        llm = FakeLLM([Tagging(tags=["ai"])])
        pipeline = Pipeline(storage, llm)
        thought = await pipeline.enrich(pipeline.write(ThoughtRequest(text="About agents")))
        assert thought.enrichment.tags == ["ai"]
        system, _ = llm.calls[-1]
        assert "- ai" in system and "- project" not in system

    def test_a_new_project_makes_no_item_a_retag_candidate(self, storage):
        untagged = Item(
            id="a", first_captured_at=T1, captured_at=T1, current_version_id="v", title="A", taxonomy_version=0
        )
        add_tag(storage, "project/other")
        assert retag_candidates([untagged], storage.get_taxonomy()) == []
        add_tag(storage, "ai")
        assert retag_candidates([untagged], storage.get_taxonomy()) == [untagged.id]
