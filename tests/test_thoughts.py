from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kb.config import THOUGHT_DERIVED_TITLE_CHARS
from kb.llm.fake import FakeLLM
from kb.models import CaptureRequest, Channel, Kind, ThoughtEdit, ThoughtRequest, VersionStatus, thought_title
from kb.normalize import thought_id
from kb.notes import write_note
from kb.owner_tags import tag_item, untag_item
from kb.pipeline.run import Pipeline
from kb.pipeline.summarise import Summary
from kb.pipeline.tag import Tagging
from kb.storage.memory import MemoryStorage
from kb.taxonomy import add_tag

T1 = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)


@pytest.fixture
def storage():
    s = MemoryStorage()
    for path in ("cooking", "ideas"):
        add_tag(s, path, f"About {path}")
    return s


def thought(text="Soup needs salt.\nMore later.", title="", tags=(), at=T1) -> ThoughtRequest:
    return ThoughtRequest(title=title, text=text, tags=list(tags), written_at=at)


class FailingLLM(FakeLLM):
    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding service down")


class TestRequest:
    def test_title_falls_back_to_the_first_line(self):
        assert thought_title("", "  First line\nsecond") == "First line"
        assert thought_title("Mine", "First line") == "Mine"
        long = thought_title("", "x" * 200)
        assert len(long) == THOUGHT_DERIVED_TITLE_CHARS and long.endswith("…")

    def test_text_is_required(self):
        with pytest.raises(ValidationError, match="needs some text"):
            ThoughtEdit(text="  \n ")

    def test_line_endings_and_whitespace_are_normalised(self):
        assert ThoughtEdit(title=" T ", text=" a\r\nb ").model_dump() == {"title": "T", "text": "a\nb", "tags": []}

    def test_a_thought_is_not_captured(self):
        with pytest.raises(ValidationError, match="written, not captured"):
            CaptureRequest(url="https://example.com", channel=Channel.WRITTEN)


class TestWrite:
    def test_shown_at_once_before_enrichment(self, storage):
        version = Pipeline(storage, FakeLLM()).write(thought())
        assert version.item_id == thought_id(T1)
        assert (version.status, version.channel, version.kind) == (
            VersionStatus.PENDING,
            Channel.WRITTEN,
            Kind.THOUGHT,
        )
        item = storage.get_item(version.item_id)
        assert (item.media_type, item.title, item.text, item.tags, item.embedding) == (
            Kind.THOUGHT,
            "Soup needs salt.",
            "Soup needs salt.\nMore later.",
            [],
            None,
        )
        assert item.first_captured_at == T1
        assert [i.id for i in storage.search("salt", None)] == [item.id]

    def test_the_same_written_at_returns_the_stored_thought(self, storage):
        pipeline = Pipeline(storage, FakeLLM())
        first = pipeline.write(thought())
        again = pipeline.write(thought(text="different"))
        assert again == first
        assert len(storage.list_versions(first.item_id)) == 1

    def test_unknown_tags_are_rejected(self, storage):
        with pytest.raises(ValueError, match="not in the taxonomy: nope"):
            Pipeline(storage, FakeLLM()).write(thought(tags=["nope"]))
        assert storage.items == {}

    async def test_enrichment_embeds_and_tags_the_text_without_summarising(self, storage):
        llm = FakeLLM(answers=[Tagging(tags=["cooking"])])
        pipeline = Pipeline(storage, llm)
        version = await pipeline.enrich(pipeline.write(thought(title="Salt")))

        assert version.status is VersionStatus.ENRICHED
        e = version.enrichment
        assert (e.tags, e.model, e.prompt_version, e.summary) == (["cooking"], None, None, "")
        assert llm.embedded == ["Salt\nSoup needs salt.\nMore later."]
        assert len(llm.calls) == 1  # the tag call only
        assert llm.calls[0][1] == "# Salt\n\nSoup needs salt.\nMore later."
        item = storage.get_item(version.item_id)
        assert (item.tags, item.text, item.current_version_id) == (["cooking"], version.text, version.id)
        assert item.embedding == e.embedding

    async def test_picked_tags_skip_the_tag_step(self, storage):
        llm = FakeLLM()
        pipeline = Pipeline(storage, llm)
        written = pipeline.write(thought(tags=["ideas"]))
        assert storage.get_item(written.item_id).tags == ["ideas"]
        version = await pipeline.enrich(written)
        assert llm.calls == []
        assert version.enrichment.tags == []
        item = storage.get_item(version.item_id)
        assert (item.tags, item.annotations.owner_tags) == (["ideas"], ["ideas"])

    async def test_a_failed_enrichment_leaves_the_thought_visible(self, storage):
        pipeline = Pipeline(storage, FailingLLM())
        version = await pipeline.enrich(pipeline.write(thought()))
        assert version.status is VersionStatus.FAILED
        item = storage.get_item(version.item_id)
        assert (item.text, item.current_version_id) == ("Soup needs salt.\nMore later.", version.id)

    async def test_retry_enriches_a_failed_version_again(self, storage):
        failed = await Pipeline(storage, FailingLLM()).enrich(Pipeline(storage, FakeLLM()).write(thought()))
        llm = FakeLLM(answers=[Tagging(tags=["cooking"])])
        pipeline = Pipeline(storage, llm)
        pending = pipeline.retry(failed.item_id)
        assert (pending.id, pending.status, pending.error) == (failed.id, VersionStatus.PENDING, None)
        await pipeline.enrich(pending)
        assert storage.get_item(failed.item_id).tags == ["cooking"]
        with pytest.raises(ValueError, match="nothing to retry"):
            pipeline.retry(failed.item_id)


class TestEdit:
    async def written(self, storage, tags=("cooking",)):
        pipeline = Pipeline(storage, FakeLLM(answers=[Tagging(tags=list(tags))]))
        return await pipeline.enrich(pipeline.write(thought()))

    async def test_adds_a_version_shown_at_once_with_the_previous_tags(self, storage):
        first = await self.written(storage)
        edited = Pipeline(storage, FakeLLM()).edit(first.item_id, ThoughtEdit(text="Soup needs pepper."))

        assert edited.item_id == first.item_id and edited.id != first.id
        assert [v.id for v in storage.list_versions(first.item_id)] == [edited.id, first.id]
        item = storage.get_item(first.item_id)
        assert (item.text, item.title, item.current_version_id) == (
            "Soup needs pepper.",
            "Soup needs pepper.",
            edited.id,
        )
        assert (item.tags, item.embedding) == (["cooking"], first.enrichment.embedding)
        assert item.first_captured_at == T1

    async def test_edited_text_is_tagged_from_scratch(self, storage):
        first = await self.written(storage)
        llm = FakeLLM(answers=[Tagging(tags=["ideas"])])
        pipeline = Pipeline(storage, llm)
        await pipeline.enrich(pipeline.edit(first.item_id, ThoughtEdit(text="A new idea.")))
        assert storage.get_item(first.item_id).tags == ["ideas"]
        assert llm.embedded == ["A new idea.\nA new idea."]

    async def test_a_title_only_edit_reuses_embedding_and_tags(self, storage):
        first = await self.written(storage)
        llm = FakeLLM()
        pipeline = Pipeline(storage, llm)
        edited = await pipeline.enrich(pipeline.edit(first.item_id, ThoughtEdit(title="Salt", text=first.text)))
        assert (llm.calls, llm.embedded) == ([], [])
        assert edited.enrichment.reused_from == first.id
        item = storage.get_item(first.item_id)
        assert (item.title, item.tags) == ("Salt", ["cooking"])

    async def test_owner_tag_decisions_survive_and_work_while_pending(self, storage):
        first = await self.written(storage, tags=["cooking", "ideas"])
        untag_item(storage, first.item_id, "ideas")
        Pipeline(storage, FakeLLM()).edit(first.item_id, ThoughtEdit(text="Pending edit."))
        assert tag_item(storage, first.item_id, "ideas").tags == ["cooking", "ideas"]
        assert untag_item(storage, first.item_id, "cooking").tags == ["ideas"]

    def test_an_edit_is_newest_even_after_a_future_written_at(self, storage):
        pipeline = Pipeline(storage, FakeLLM())
        first = pipeline.write(thought(at=datetime(2099, 1, 1, tzinfo=UTC)))
        edited = pipeline.edit(first.item_id, ThoughtEdit(text="Later."))
        assert edited.captured_at > first.captured_at
        assert storage.get_item(first.item_id).text == "Later."

    async def test_an_article_cannot_be_edited_as_a_thought(self, storage):
        llm = FakeLLM(answers=[Summary(title="A", summary="S"), Tagging(tags=[])])
        pipeline = Pipeline(storage, llm)
        article = await pipeline.enrich(
            await pipeline.capture(CaptureRequest(url="https://example.com/a", content="<p>hi</p>", channel="manual"))
        )
        with pytest.raises(ValueError, match="only a Thought"):
            pipeline.edit(article.item_id, ThoughtEdit(text="x"))
        assert pipeline.edit("nope", ThoughtEdit(text="x")) is None

    async def test_a_thought_has_no_note(self, storage):
        first = await self.written(storage)
        with pytest.raises(ValueError, match="no note"):
            write_note(storage, first.item_id, "hmm")


async def test_retag_includes_thoughts(storage):
    first = await TestEdit().written(storage, tags=[])
    add_tag(storage, "cooking/soup", "Soups")
    llm = FakeLLM(answers=[Tagging(tags=["cooking/soup"])])
    retagged = await Pipeline(storage, llm).retag(first.item_id)
    assert (retagged.channel, retagged.kind, retagged.text) == (Channel.RETAG, Kind.THOUGHT, first.text)
    assert llm.calls[0][1].startswith("# Soup needs salt.\n\nSoup needs salt.")
    item = storage.get_item(first.item_id)
    assert (item.tags, item.current_version_id, item.text) == (["cooking/soup"], retagged.id, first.text)


async def test_retag_skips_a_thought_whose_edit_is_pending(storage):
    first = await TestEdit().written(storage)
    Pipeline(storage, FakeLLM()).edit(first.item_id, ThoughtEdit(text="Pending."))
    assert await Pipeline(storage, FakeLLM()).retag(first.item_id) is None
