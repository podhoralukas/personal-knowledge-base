from datetime import UTC, datetime

from kb.llm.fake import FakeLLM
from kb.models import CaptureRequest, Channel, Enrichment, Item, Version
from kb.search import search
from kb.storage.memory import MemoryStorage


async def stored(storage: MemoryStorage, llm: FakeLLM, title: str) -> Item:
    enrichment = Enrichment(
        title=title,
        summary="plain text",
        embedding=await llm.embed(title),
        model="m",
        prompt_version="1",
        taxonomy_version=0,
        embedding_model="e",
    )
    version = Version.create(
        CaptureRequest(url=f"https://example.com/{len(storage.items)}", channel=Channel.MANUAL),
        datetime(2026, 10, 1, tzinfo=UTC),
        "text",
    ).enriched(enrichment)
    item = Item.from_version(version)
    storage.put_item(item)
    return item


async def test_query_is_embedded_and_matched_by_meaning():
    storage, llm = MemoryStorage(), FakeLLM()
    target = await stored(storage, llm, "Navier Stokes")
    await stored(storage, llm, "Tomato soup")
    llm.embedded.clear()

    results = await search(storage, llm, "Navier Stokes")

    assert llm.embedded == ["Navier Stokes"]
    assert results.semantic is True
    assert results.items[0].id == target.id


async def test_failed_embedding_falls_back_to_keywords():
    storage, llm = MemoryStorage(), FakeLLM()
    target = await stored(storage, llm, "Navier Stokes")
    await stored(storage, llm, "Tomato soup")

    async def broken(text):
        raise RuntimeError("provider down")

    llm.embed = broken
    results = await search(storage, llm, "stokes")

    assert results.semantic is False
    assert [i.id for i in results.items] == [target.id]
