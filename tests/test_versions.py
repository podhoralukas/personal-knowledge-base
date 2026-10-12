from datetime import UTC, datetime

import pytest

from kb.llm.fake import FakeLLM
from kb.models import CaptureRequest, Channel, ThoughtEdit, ThoughtRequest
from kb.owner_tags import untag_item
from kb.pipeline.run import Pipeline
from kb.pipeline.summarise import Summary
from kb.pipeline.tag import Tagging
from kb.storage.memory import MemoryStorage
from kb.taxonomy import add_tag
from kb.versions import LastVersion, delete_version

T1 = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
T3 = datetime(2026, 9, 1, 11, 0, 0, tzinfo=UTC)


@pytest.fixture
def storage():
    s = MemoryStorage()
    for path in ("ai", "cooking"):
        add_tag(s, path, path)
    return s


def capture(at, note="", content="<p>hello</p>") -> CaptureRequest:
    return CaptureRequest(
        url="https://example.com/a", content=content, captured_at=at, channel=Channel.MANUAL, note=note
    )


async def captured(storage, *requests, tags=("ai",)):
    """Enrich each Capture in turn; each gets its own summary and tags."""
    answers = []
    for r in requests:
        answers += [Summary(title=f"Title {r.captured_at:%H}", summary=r.content), Tagging(tags=list(tags))]
    pipeline = Pipeline(storage, FakeLLM(answers=answers))
    return [await pipeline.enrich(await pipeline.capture(r)) for r in requests]


async def test_deleting_an_older_version_keeps_the_current_view(storage):
    v1, v2 = await captured(storage, capture(T1), capture(T2, content="<p>changed</p>"))
    assert delete_version(storage, v1.id) is True
    assert storage.list_versions(v1.item_id) == [v2]
    item = storage.get_item(v1.item_id)
    assert (item.current_version_id, item.title, item.first_captured_at) == (v2.id, "Title 10", T1)


async def test_deleting_the_current_version_falls_back_to_the_newest_remaining(storage):
    v1, v2 = await captured(storage, capture(T1, note="first"), capture(T2, note="second", content="<p>changed</p>"))
    untag_item(storage, v1.item_id, "ai")
    delete_version(storage, v2.id)
    item = storage.get_item(v1.item_id)
    assert (item.current_version_id, item.title, item.summary) == (v1.id, "Title 09", v1.enrichment.summary)
    assert item.annotations.notes == "first\n\nsecond"  # Annotations are not versioned
    assert (item.tags, item.annotations.rejected_tags) == ([], ["ai"])
    assert item.first_captured_at == T1


async def test_the_last_version_cannot_be_deleted(storage):
    (v1,) = await captured(storage, capture(T1))
    with pytest.raises(LastVersion):
        delete_version(storage, v1.id)
    assert storage.get_version(v1.id) == v1


async def test_an_articles_last_enriched_version_cannot_be_deleted(storage):
    (v1,) = await captured(storage, capture(T1))
    pending = await Pipeline(storage, FakeLLM()).capture(capture(T2))
    with pytest.raises(LastVersion):
        delete_version(storage, v1.id)
    assert delete_version(storage, pending.id) is True


def test_unknown_version(storage):
    assert delete_version(storage, "nope") is False


async def test_a_deleted_pending_version_drops_its_result(storage):
    (v1,) = await captured(storage, capture(T1))
    pipeline = Pipeline(storage, FakeLLM(answers=[Summary(title="Late", summary="S"), Tagging(tags=[])]))
    pending = await pipeline.capture(capture(T2, content="<p>new</p>"))
    delete_version(storage, pending.id)
    await pipeline.enrich(pending)
    assert storage.get_version(pending.id) is None
    assert storage.get_item(v1.item_id).current_version_id == v1.id


async def test_deleting_a_thoughts_bad_edit_restores_the_previous_text(storage):
    pipeline = Pipeline(storage, FakeLLM(answers=[Tagging(tags=["cooking"]), Tagging(tags=["ai"])]))
    first = await pipeline.enrich(pipeline.write(ThoughtRequest(text="Good text", written_at=T1)))
    bad = await pipeline.enrich(pipeline.edit(first.item_id, ThoughtEdit(text="Bad text")))
    assert storage.get_item(first.item_id).tags == ["ai"]

    delete_version(storage, bad.id)
    item = storage.get_item(first.item_id)
    assert (item.text, item.tags, item.current_version_id) == ("Good text", ["cooking"], first.id)
    assert item.embedding == first.enrichment.embedding


async def test_deleting_a_thoughts_enriched_version_under_a_pending_edit(storage):
    pipeline = Pipeline(storage, FakeLLM(answers=[Tagging(tags=["cooking"])]))
    first = await pipeline.enrich(pipeline.write(ThoughtRequest(text="One", written_at=T1)))
    pending = pipeline.edit(first.item_id, ThoughtEdit(text="Two"))
    delete_version(storage, first.id)
    item = storage.get_item(first.item_id)
    assert (item.text, item.tags, item.embedding, item.current_version_id) == ("Two", [], None, pending.id)
