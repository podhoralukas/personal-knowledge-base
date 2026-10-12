from datetime import UTC, date, datetime

import pytest

from kb.llm.fake import FakeLLM
from kb.models import CaptureRequest, Channel, VersionStatus
from kb.pipeline.run import Pipeline
from kb.pipeline.summarise import PROMPT_VERSION, Summary
from kb.pipeline.tag import PROMPT_VERSION as TAG_PROMPT_VERSION
from kb.pipeline.tag import Tagging
from kb.storage.memory import MemoryStorage
from kb.taxonomy import add_tag

T1 = datetime(2026, 9, 21, 14, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 9, 21, 15, 0, 0, tzinfo=UTC)

HTML = """<html><body><article><h1>Hello</h1>
<p>World. This paragraph is here so the page looks like a real article to the crawler.</p></article></body></html>"""


def summary(title="Hello") -> Summary:
    return Summary(
        title=title,
        summary="It greets the world.",
        key_points=["hello"],
        published_date=date(2026, 9, 1),
        language="en",
    )


def request(at=T1, content=HTML, url="https://example.com/a") -> CaptureRequest:
    return CaptureRequest(url=url, content=content, captured_at=at, channel=Channel.EXTENSION)


@pytest.fixture
def storage():
    return MemoryStorage()


async def test_capture_stores_pending_version_with_markdown(storage):
    pipeline = Pipeline(storage, FakeLLM())
    version = await pipeline.capture(request())
    assert version.status is VersionStatus.PENDING
    assert version.content.startswith("# Hello")
    assert storage.get_version(version.id) == version
    assert storage.get_item(version.item_id) is None


async def test_enrich_completes_version_and_creates_item(storage):
    llm = FakeLLM(answers=[summary()])
    pipeline = Pipeline(storage, llm)
    version = await pipeline.enrich(await pipeline.capture(request()))

    assert version.status is VersionStatus.ENRICHED
    assert version.content is None
    e = version.enrichment
    assert (e.title, e.summary, e.key_points, e.published_date, e.language) == (
        "Hello",
        "It greets the world.",
        ["hello"],
        date(2026, 9, 1),
        "en",
    )
    assert e.tags == []
    assert len(e.embedding) == 1536
    assert (e.model, e.prompt_version, e.taxonomy_version, e.embedding_model) == (
        "fake-llm",
        PROMPT_VERSION,
        0,
        "fake-embedding",
    )
    assert e.reused_from is None

    assert llm.embedded == ["Hello\nIt greets the world."]
    assert storage.get_version(version.id) == version
    item = storage.get_item(version.item_id)
    assert item.current_version_id == version.id
    assert item.title == "Hello"


async def test_unchanged_content_reuses_previous_enrichment(storage):
    llm = FakeLLM(answers=[summary()])
    pipeline = Pipeline(storage, llm)
    first = await pipeline.enrich(await pipeline.capture(request(at=T1)))
    second = await pipeline.enrich(await pipeline.capture(request(at=T2)))

    assert second.status is VersionStatus.ENRICHED
    assert second.enrichment.reused_from == first.id
    assert second.enrichment.summary == first.enrichment.summary
    assert len(llm.calls) == 1
    assert storage.get_item(first.item_id).current_version_id == second.id
    assert storage.get_item(first.item_id).first_captured_at == T1


async def test_reuse_points_at_the_original_not_the_chain(storage):
    pipeline = Pipeline(storage, FakeLLM(answers=[summary()]))
    first = await pipeline.enrich(await pipeline.capture(request(at=T1)))
    await pipeline.enrich(await pipeline.capture(request(at=T2)))
    third = await pipeline.enrich(await pipeline.capture(request(at=datetime(2026, 9, 22, tzinfo=UTC))))
    assert third.enrichment.reused_from == first.id


async def test_changed_content_is_summarised_again(storage):
    llm = FakeLLM(answers=[summary(), summary(title="Hello v2")])
    pipeline = Pipeline(storage, llm)
    await pipeline.enrich(await pipeline.capture(request(at=T1)))
    second = await pipeline.enrich(await pipeline.capture(request(at=T2, content=HTML.replace("World", "Moon"))))
    assert second.enrichment.reused_from is None
    assert second.enrichment.title == "Hello v2"
    assert len(llm.calls) == 2


async def test_changed_summary_inputs_are_not_reused(storage):
    llm = FakeLLM(answers=[summary(), summary()])
    pipeline = Pipeline(storage, llm)
    await pipeline.enrich(await pipeline.capture(request(at=T1)))
    llm.model = "other-llm"
    second = await pipeline.enrich(await pipeline.capture(request(at=T2)))
    assert second.enrichment.reused_from is None
    assert second.enrichment.model == "other-llm"
    assert len(llm.calls) == 2


def taxonomy(storage, *paths):
    for path in paths:
        add_tag(storage, path, f"About {path}")


async def test_empty_taxonomy_skips_the_tag_call(storage):
    llm = FakeLLM(answers=[summary()])
    version = await Pipeline(storage, llm).enrich(await Pipeline(storage, llm).capture(request()))
    assert version.enrichment.tags == []
    assert (version.enrichment.tag_model, version.enrichment.tag_prompt_version) == ("fake-llm", TAG_PROMPT_VERSION)
    assert len(llm.calls) == 1


async def test_tags_are_chosen_from_the_taxonomy_over_the_summary(storage):
    taxonomy(storage, "ai", "ai/rag", "cooking")
    llm = FakeLLM(answers=[summary(), Tagging(tags=["cooking", "ai/rag", "made/up"])])
    pipeline = Pipeline(storage, llm)
    version = await pipeline.enrich(await pipeline.capture(request()))

    assert version.enrichment.tags == ["ai/rag", "cooking"]
    assert version.enrichment.taxonomy_version == 3
    item = storage.get_item(version.item_id)
    assert (item.tags, item.taxonomy_version) == (["ai/rag", "cooking"], 3)

    system, user = llm.calls[1]
    assert "- ai/rag: About ai/rag" in system
    assert user.startswith("# Hello\n\nIt greets the world.")
    assert "World. This paragraph" not in user


async def test_unchanged_content_with_newer_taxonomy_reuses_summary_and_retags(storage):
    taxonomy(storage, "ai")
    llm = FakeLLM(answers=[summary(), Tagging(tags=["ai"]), Tagging(tags=["ai/rag"])])
    pipeline = Pipeline(storage, llm)
    first = await pipeline.enrich(await pipeline.capture(request(at=T1)))
    taxonomy(storage, "ai/rag")
    second = await pipeline.enrich(await pipeline.capture(request(at=T2)))

    assert second.enrichment.reused_from == first.id
    assert (second.enrichment.tags, second.enrichment.taxonomy_version) == (["ai/rag"], 2)
    assert len(llm.calls) == 3  # summary, tag, tag
    assert llm.embedded == ["Hello\nIt greets the world."]


async def test_unchanged_content_and_taxonomy_reuses_everything(storage):
    taxonomy(storage, "ai")
    llm = FakeLLM(answers=[summary(), Tagging(tags=["ai"])])
    pipeline = Pipeline(storage, llm)
    await pipeline.enrich(await pipeline.capture(request(at=T1)))
    second = await pipeline.enrich(await pipeline.capture(request(at=T2)))
    assert second.enrichment.tags == ["ai"]
    assert len(llm.calls) == 2


async def test_retag_appends_a_version_from_the_current_summary(storage):
    taxonomy(storage, "ai")
    llm = FakeLLM(answers=[summary(), Tagging(tags=[]), Tagging(tags=["ai/rag"])])
    pipeline = Pipeline(storage, llm)
    first = await pipeline.enrich(await pipeline.capture(request(at=T1)))
    taxonomy(storage, "ai/rag")

    retagged = await pipeline.retag(first.item_id)

    assert retagged.channel is Channel.RETAG
    assert retagged.captured_at > first.captured_at
    assert retagged.status is VersionStatus.ENRICHED
    assert (retagged.content_hash, retagged.original_url) == (first.content_hash, first.original_url)
    e = retagged.enrichment
    assert (e.tags, e.taxonomy_version, e.reused_from) == (["ai/rag"], 2, first.id)
    assert (e.summary, e.embedding) == (first.enrichment.summary, first.enrichment.embedding)
    assert first.enrichment.tags == [] and storage.get_version(first.id).enrichment.tags == []

    assert [v.id for v in storage.list_versions(first.item_id)] == [retagged.id, first.id]
    item = storage.get_item(first.item_id)
    assert (item.current_version_id, item.tags, item.first_captured_at) == (retagged.id, ["ai/rag"], T1)


async def test_enrichment_of_a_deleted_capture_is_dropped(storage):
    pipeline = Pipeline(storage, FakeLLM(answers=[summary()]))
    version = await pipeline.capture(request())
    storage.delete_item(version.item_id)

    await pipeline.enrich(version)

    assert storage.get_version(version.id) is None
    assert storage.get_item(version.item_id) is None


async def test_failed_enrichment_of_a_deleted_capture_is_dropped(storage):
    pipeline = Pipeline(storage, FakeLLM(answers=[]))
    version = await pipeline.capture(request())
    storage.delete_item(version.item_id)

    await pipeline.enrich(version)

    assert storage.list_versions(version.item_id) == []


async def test_retag_of_an_item_deleted_meanwhile_is_dropped(storage, monkeypatch):
    llm = FakeLLM(answers=[summary(), Tagging(tags=["ai"])])
    pipeline = Pipeline(storage, llm)
    first = await pipeline.enrich(await pipeline.capture(request()))
    taxonomy(storage, "ai")
    get_taxonomy = storage.get_taxonomy

    def delete_then_get_taxonomy():
        storage.delete_item(first.item_id)
        return get_taxonomy()

    monkeypatch.setattr(storage, "get_taxonomy", delete_then_get_taxonomy)

    assert await pipeline.retag(first.item_id) is None
    assert storage.get_item(first.item_id) is None
    assert storage.list_versions(first.item_id) == []


async def test_retag_unknown_item_is_none(storage):
    assert await Pipeline(storage, FakeLLM()).retag("nope") is None


async def test_retag_all_skips_failures(storage):
    llm = FakeLLM(answers=[summary(), summary(title="B")])
    pipeline = Pipeline(storage, llm)
    a = await pipeline.enrich(await pipeline.capture(request(url="https://example.com/a")))
    b = await pipeline.enrich(await pipeline.capture(request(url="https://example.com/b")))
    taxonomy(storage, "ai")
    llm.answers = [Tagging(tags=["ai"])]  # the second re-tag finds no answer and fails

    await pipeline.retag_all([a.item_id, b.item_id])

    assert storage.get_item(a.item_id).tags == ["ai"]
    assert storage.get_item(b.item_id).current_version_id == b.id
    assert len(storage.list_versions(b.item_id)) == 1


async def test_llm_failure_is_recorded_on_the_version(storage):
    pipeline = Pipeline(storage, FakeLLM(answers=[]))  # pop from empty list raises
    version = await pipeline.enrich(await pipeline.capture(request()))
    assert version.status is VersionStatus.FAILED
    assert "IndexError" in version.error
    assert version.content is not None
    assert storage.get_version(version.id).status is VersionStatus.FAILED
    assert storage.get_item(version.item_id) is None


async def test_invalid_url_is_rejected_before_fetching(storage, monkeypatch):
    from kb.pipeline import run

    async def fail_fetch(url):
        raise AssertionError("must not fetch")

    monkeypatch.setattr(run, "fetch", fail_fetch)
    with pytest.raises(ValueError, match="not an absolute http"):
        await Pipeline(storage, FakeLLM()).capture(request(content=None, url="not a url"))


async def test_capture_without_content_fetches_and_uses_final_url(storage, monkeypatch):
    from kb.pipeline import run
    from kb.pipeline.fetch import Fetched

    async def fake_fetch(url):
        return Fetched(url="https://example.com/final", markdown="# fetched")

    monkeypatch.setattr(run, "fetch", fake_fetch)
    version = await Pipeline(storage, FakeLLM()).capture(request(content=None, url="https://example.com/old"))
    assert version.original_url == "https://example.com/final"
    assert version.content == "# fetched"


async def test_picked_tags_skip_the_tag_step_and_become_owner_tags(storage):
    taxonomy(storage, "ai", "ai/rag")
    llm = FakeLLM(answers=[summary()])  # no Tagging answer: a tag call would fail the enrichment
    pipeline = Pipeline(storage, llm)
    picked = CaptureRequest(url="https://example.com/a", content=HTML, channel=Channel.EXTENSION, tags=["ai/rag"])
    version = await pipeline.enrich(await pipeline.capture(picked))

    assert version.status is VersionStatus.ENRICHED
    assert (version.owner_tags, version.enrichment.tags, version.enrichment.taxonomy_version) == (["ai/rag"], [], 2)
    item = storage.get_item(version.item_id)
    assert (item.tags, item.annotations.owner_tags) == (["ai/rag"], ["ai/rag"])
    assert len(llm.calls) == 1


async def test_the_note_reaches_the_item_but_never_the_llm(storage):
    taxonomy(storage, "ai")
    llm = FakeLLM(answers=[summary(), Tagging(tags=["ai"])])
    pipeline = Pipeline(storage, llm)
    noted = request().model_copy(update={"note": "secret-ish remark"})
    version = await pipeline.enrich(await pipeline.capture(noted))

    assert version.note == "secret-ish remark"
    assert storage.get_item(version.item_id).annotations.notes == "secret-ish remark"
    assert all("secret-ish" not in str(call) for call in llm.calls)


async def test_picked_tags_must_be_in_the_taxonomy(storage):
    taxonomy(storage, "ai")
    picked = CaptureRequest(url="https://example.com/a", content=HTML, channel=Channel.EXTENSION, tags=["ai", "nope"])
    with pytest.raises(ValueError, match="not in the taxonomy: nope"):
        await Pipeline(storage, FakeLLM()).capture(picked)


async def test_owner_decisions_survive_a_new_capture(storage):
    from kb.owner_tags import tag_item, untag_item

    taxonomy(storage, "ai", "cooking")
    llm = FakeLLM(answers=[summary(), Tagging(tags=["cooking"])])
    pipeline = Pipeline(storage, llm)
    first = await pipeline.enrich(await pipeline.capture(request()))
    untag_item(storage, first.item_id, "cooking")
    tag_item(storage, first.item_id, "ai")

    llm.answers = [summary(title="Changed"), Tagging(tags=[])]
    await pipeline.enrich(await pipeline.capture(request(at=T2, content=HTML.replace("World", "Earth"))))

    offered = llm.calls[-1][0]
    assert "- ai:" in offered and "cooking" not in offered  # a rejected tag is never offered again
    item = storage.get_item(first.item_id)
    assert (item.title, item.tags) == ("Changed", ["ai"])
    assert (item.annotations.owner_tags, item.annotations.rejected_tags) == (["ai"], ["cooking"])


async def test_retag_only_adds_and_skips_rejected_tags(storage):
    from kb.owner_tags import untag_item

    taxonomy(storage, "ai", "cooking", "travel")
    llm = FakeLLM(answers=[summary(), Tagging(tags=["cooking", "travel"])])
    pipeline = Pipeline(storage, llm)
    first = await pipeline.enrich(await pipeline.capture(request()))
    untag_item(storage, first.item_id, "travel")

    llm.answers = [Tagging(tags=["ai"])]
    retagged = await pipeline.retag(first.item_id)

    assert "travel" not in llm.calls[-1][0]
    assert retagged.enrichment.tags == ["ai", "cooking", "travel"]  # the pipeline's own record keeps everything
    assert storage.get_item(first.item_id).tags == ["ai", "cooking"]  # minus the Owner's rejection
