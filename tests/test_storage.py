"""One behavioural suite, run against every Storage implementation."""

import copy
from datetime import UTC, datetime

import pytest
from opensearchpy import OpenSearch

from kb.models import (
    Annotations,
    CaptureRequest,
    Channel,
    DateRange,
    Enrichment,
    Item,
    Kind,
    Tag,
    ThoughtEdit,
    Version,
)
from kb.normalize import thought_id
from kb.storage import TagExists, mappings
from kb.storage.memory import MemoryStorage
from kb.storage.opensearch import OpenSearchStorage

T1 = datetime(2026, 9, 21, 14, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 9, 21, 15, 0, 0, tzinfo=UTC)
T3 = datetime(2026, 9, 22, 9, 0, 0, tzinfo=UTC)


def version(url: str, at: datetime, content: str = "text") -> Version:
    return Version.create(CaptureRequest(url=url, channel=Channel.MANUAL), at, content)


def enrichment(tags: list[str] | None = None, taxonomy_version: int = 0) -> Enrichment:
    return Enrichment(
        title="T",
        summary="S",
        key_points=["k"],
        tags=["ai"] if tags is None else tags,
        embedding=[0.5] * 1536,
        model="m",
        prompt_version="1",
        taxonomy_version=taxonomy_version,
        embedding_model="e",
        tag_model="m",
        tag_prompt_version="1",
    )


# The KB's own cluster from docker-compose.yml; tests use prefixed indices and delete them afterwards.
OPENSEARCH_URL = "http://localhost:9201"


def opensearch_client() -> OpenSearch | None:
    client = OpenSearch(hosts=[OPENSEARCH_URL], timeout=2)
    try:
        client.info()
    except Exception:
        return None
    return client


@pytest.fixture(params=["memory", "opensearch"])
def storage(request):
    if request.param == "memory":
        yield MemoryStorage()
        return

    client = opensearch_client()
    if client is None:
        pytest.skip(f"OpenSearch not reachable on {OPENSEARCH_URL}")
    store = OpenSearchStorage(client, index_prefix="test_")
    indices = (store.items_index, store.versions_index, store.taxonomy_index)
    for index in indices:
        client.indices.delete(index=index, ignore_unavailable=True)
    store.ensure_indices()
    yield store
    for index in indices:
        client.indices.delete(index=index, ignore_unavailable=True)
    delete_search_pipeline(store)


def delete_search_pipeline(store: OpenSearchStorage) -> None:
    store.client.transport.perform_request("DELETE", f"/_search/pipeline/{store.search_pipeline}")


def test_missing_documents_are_none(storage):
    assert storage.get_version("nope") is None
    assert storage.get_item("nope") is None
    assert storage.list_versions("nope") == []


def test_version_round_trip(storage):
    v = version("https://example.com/a", T1, "# hello")
    storage.put_version(v)
    assert storage.get_version(v.id) == v

    picked = Version.create(
        CaptureRequest(url="https://example.com/b", channel=Channel.EXTENSION, tags=["ai"]), T1, "x"
    )
    storage.put_version(picked)
    assert storage.get_version(picked.id).owner_tags == ["ai"]


def test_enriched_version_round_trip(storage):
    v = version("https://example.com/a", T1).enriched(enrichment())
    storage.put_version(v)
    assert storage.get_version(v.id) == v


def test_put_version_twice_completes_the_stub(storage):
    stub = version("https://example.com/a", T1, "# hello")
    storage.put_version(stub)
    storage.put_version(stub.enriched(enrichment()))
    stored = storage.get_version(stub.id)
    assert stored.content is None
    assert stored.enrichment is not None
    assert len(storage.list_versions(stub.item_id)) == 1


def test_list_versions_is_newest_first_and_per_item(storage):
    a1, a2, a3 = (version("https://example.com/a", t) for t in (T1, T3, T2))
    b1 = version("https://example.com/b", T1)
    for v in (a1, a2, a3, b1):
        storage.put_version(v)
    assert [v.captured_at for v in storage.list_versions(a1.item_id)] == [T3, T2, T1]
    assert storage.list_versions(b1.item_id) == [b1]


def test_item_round_trip_and_upsert(storage):
    v1 = version("https://example.com/a", T1).enriched(enrichment())
    annotations = Annotations(notes="mine", owner_tags=["ai/rag"], rejected_tags=["cooking"])
    item = Item.from_version(v1).model_copy(update={"annotations": annotations})
    storage.put_item(item)
    assert storage.get_item(item.id) == item

    v2 = version("https://example.com/a", T2).enriched(enrichment())
    storage.put_item(Item.from_version(v2, previous=item))
    stored = storage.get_item(item.id)
    assert stored.current_version_id == v2.id
    assert stored.first_captured_at == T1
    assert stored.annotations == annotations


def test_delete_item_removes_its_versions_only(storage):
    a1, a2 = version("https://example.com/a", T1), version("https://example.com/a", T2).enriched(enrichment())
    b1 = version("https://example.com/b", T1).enriched(enrichment())
    for v in (a1, a2, b1):
        storage.put_version(v)
    storage.put_item(Item.from_version(a2))
    storage.put_item(Item.from_version(b1))

    assert storage.delete_item(a1.item_id) is True
    assert storage.get_item(a1.item_id) is None
    assert storage.list_versions(a1.item_id) == []
    assert storage.get_version(a1.id) is None
    assert storage.get_item(b1.item_id) is not None
    assert storage.list_versions(b1.item_id) == [b1]


def test_delete_item_without_item_doc_removes_pending_versions(storage):
    pending = version("https://example.com/a", T1)
    storage.put_version(pending)
    assert storage.delete_item(pending.item_id) is True
    assert storage.get_version(pending.id) is None


def test_delete_unknown_item_is_false(storage):
    assert storage.delete_item("nope") is False


def item(url: str, at: datetime, tags: list[str], taxonomy_version: int = 0) -> Item:
    return Item.from_version(version(url, at).enriched(enrichment(tags, taxonomy_version)))


def test_list_item_ids_and_items_tagged_before_a_taxonomy_version(storage):
    old, mid, new = (item(f"https://example.com/{n}", T1, ["ai"], tv) for n, tv in (("old", 1), ("mid", 2), ("new", 3)))
    for i in (old, mid, new):
        storage.put_item(i)
    assert sorted(storage.list_item_ids()) == sorted([old.id, mid.id, new.id])
    older = storage.list_items_tagged_before(3)
    assert sorted(i.id for i in older) == sorted([old.id, mid.id])
    assert all(i.embedding is None and i.tags == ["ai"] for i in older)
    assert storage.list_items_tagged_before(1) == []


def test_list_untagged_items_newest_first_without_embeddings(storage):
    tagged = item("https://example.com/tagged", T3, ["ai"])
    older, newer = item("https://example.com/a", T1, []), item("https://example.com/b", T2, [])
    for i in (older, tagged, newer):
        storage.put_item(i)
    untagged = storage.list_untagged_items()
    assert [i.id for i in untagged] == [newer.id, older.id]
    assert all(i.embedding is None for i in untagged)


def test_list_items_newest_first_filtered_by_tag_subtree(storage):
    rag = item("https://example.com/rag", T1, ["ai/rag"])
    ai = item("https://example.com/ai", T2, ["ai", "cooking"])
    aix = item("https://example.com/aix", T3, ["aix"])  # shares the prefix "ai" but is not under ai/
    for i in (rag, ai, aix):
        storage.put_item(i)
    assert [i.id for i in storage.list_items()] == [aix.id, ai.id, rag.id]
    assert [i.id for i in storage.list_items(tag="ai")] == [ai.id, rag.id]
    assert [i.id for i in storage.list_items(tag="ai/rag")] == [rag.id]
    assert storage.list_items(tag="nope") == []
    assert all(i.embedding is None for i in storage.list_items())


def test_count_items_per_tag_subtree(storage):
    for i in (
        item("https://example.com/rag", T1, ["ai/rag"]),
        item("https://example.com/both", T1, ["ai", "ai/rag"]),  # counted once under ai
        item("https://example.com/aix", T1, ["aix"]),
    ):
        storage.put_item(i)
    assert storage.count_items(["ai", "ai/rag", "aix", "cooking"]) == {"ai": 2, "ai/rag": 2, "aix": 1, "cooking": 0}
    assert storage.count_items([]) == {}


def test_lists_order_by_saved_date_and_filter_by_saved_range(storage):
    old = item("https://example.com/old", T1, ["ai"])  # saved 2026-09-21 14:00
    new = item("https://example.com/new", T3, [])  # saved 2026-09-22 09:00
    # A later Version (e.g. a re-tag) of the old Item must not make it the newest saved.
    later = version("https://example.com/old", datetime(2026, 9, 30, tzinfo=UTC)).enriched(enrichment(["ai"]))
    old = Item.from_version(later, previous=old)
    for i in (old, new):
        storage.put_item(i)

    assert [i.id for i in storage.list_items()] == [new.id, old.id]
    day21, day22 = DateRange(start="2026-09-21", end="2026-09-21"), DateRange(start="2026-09-22")
    assert [i.id for i in storage.list_items(saved=day21)] == [old.id]
    assert [i.id for i in storage.list_items(saved=day22)] == [new.id]
    assert [i.id for i in storage.list_items(saved=DateRange(end="2026-09-20"))] == []
    assert [i.id for i in storage.list_items(tag="ai", saved=day22)] == []
    assert [i.id for i in storage.list_untagged_items(saved=day22)] == [new.id]
    assert storage.list_untagged_items(saved=day21) == []


def axis(i: int) -> list[float]:
    v = [0.0] * 1536
    v[i] = 1.0
    return v


def searchable(url: str, title: str, tags: list[str], embedding: list[float]) -> Item:
    return item(url, T1, tags).model_copy(update={"title": title, "summary": "plain text", "embedding": embedding})


@pytest.fixture
def corpus(storage):
    twin = searchable("https://example.com/twin", "Vector twin", ["ai"], axis(0))
    keyword = searchable("https://example.com/ns", "Navier Stokes blow up", ["ai/research"], axis(1))
    neither = searchable("https://example.com/soup", "Tomato soup", ["cooking"], axis(2))
    for i in (twin, keyword, neither):
        storage.put_item(i)
    return twin, keyword, neither


def test_hybrid_search_finds_keyword_and_vector_matches_first(storage, corpus):
    twin, keyword, neither = corpus
    results = storage.search("navier stokes", axis(0))
    assert {i.id for i in results[:2]} == {twin.id, keyword.id}
    assert [i.id for i in results[2:]] in ([], [neither.id])
    assert all("embedding" not in i.model_dump() for i in results)


def test_search_filters_by_tag_subtree(storage, corpus):
    twin, keyword, _ = corpus
    assert {i.id for i in storage.search("navier stokes", axis(0), tag="ai")} == {twin.id, keyword.id}
    assert [i.id for i in storage.search("navier stokes", axis(0), tag="ai/research")] == [keyword.id]


def test_search_filters_by_saved_range(storage, corpus):
    twin, keyword, _ = corpus  # all saved on 2026-09-21
    newer = keyword.model_copy(update={"first_captured_at": T3})
    storage.put_item(newer)
    day22 = DateRange(start="2026-09-22")
    assert [i.id for i in storage.search("navier stokes", axis(0), saved=day22)] == [newer.id]
    assert [i.id for i in storage.search("navier stokes", None, saved=day22)] == [newer.id]
    assert [i.id for i in storage.search("vector twin", axis(0), tag="ai", saved=DateRange(end="2026-09-21"))][
        0
    ] == twin.id


def test_keyword_search_matches_the_note(storage, corpus):
    _, _, soup = corpus
    storage.put_item(soup.model_copy(update={"annotations": Annotations(notes="grandma zebra recipe")}))
    assert [i.id for i in storage.search("zebra", None)] == [soup.id]


def test_version_keeps_its_note(storage):
    request = CaptureRequest(url="https://example.com/n", channel=Channel.EXTENSION, note="why I saved it")
    v = Version.create(request, T1, "text")
    storage.put_version(v)
    assert storage.get_version(v.id).note == "why I saved it"


def test_keyword_only_search_without_vector(storage, corpus):
    _, keyword, _ = corpus
    assert [i.id for i in storage.search("navier stokes", None)] == [keyword.id]
    assert storage.search("zebra", None) == []


def tag(path: str, taxonomy_version: int, description: str = "") -> Tag:
    return Tag(path=path, description=description, created_at=T1, created_in_taxonomy_version=taxonomy_version)


def test_empty_taxonomy_has_version_zero(storage):
    taxonomy = storage.get_taxonomy()
    assert taxonomy.tags == []
    assert taxonomy.version == 0


def test_taxonomy_version_counter_increments(storage):
    assert [storage.next_taxonomy_version() for _ in range(3)] == [1, 2, 3]


def test_tags_round_trip_sorted_by_path(storage):
    for t in (tag("ai/retrieval", 2, "Search and RAG"), tag("ai", 1), tag("ai/agents", 3)):
        storage.put_tag(t)
    taxonomy = storage.get_taxonomy()
    assert [t.path for t in taxonomy.tags] == ["ai", "ai/agents", "ai/retrieval"]
    assert taxonomy.get("ai/retrieval") == tag("ai/retrieval", 2, "Search and RAG")
    assert taxonomy.version == 3


def test_counter_document_is_not_a_tag(storage):
    storage.next_taxonomy_version()
    storage.put_tag(tag("ai", 1))
    assert [t.path for t in storage.get_taxonomy().tags] == ["ai"]


def test_put_existing_tag_is_rejected(storage):
    storage.put_tag(tag("ai", 1))
    with pytest.raises(TagExists):
        storage.put_tag(tag("ai", 2, "other"))
    assert storage.get_taxonomy().get("ai").description == ""


def test_update_and_delete_tag(storage):
    storage.put_tag(tag("ai", 1))
    storage.put_tag(tag("cooking", 2))
    storage.update_tag(tag("ai", 1, "Artificial intelligence"))
    storage.delete_tag("cooking")
    taxonomy = storage.get_taxonomy()
    assert [(t.path, t.description) for t in taxonomy.tags] == [("ai", "Artificial intelligence")]


def test_rename_tag_everywhere(storage):
    for path, v in (("ai", 1), ("ai/rag", 2), ("ai/rag/hybrid", 3), ("aix", 4), ("ml", 5)):
        storage.put_tag(tag(path, v, f"About {path}"))
    pending = Version.create(
        CaptureRequest(url="https://example.com/p", channel=Channel.EXTENSION, tags=["ai/rag"]), T1, "x"
    )
    v = version("https://example.com/a", T1).enriched(enrichment(["ai/rag/hybrid", "aix"]))
    annotations = Annotations(owner_tags=["ai"], rejected_tags=["ai/rag"])
    item = Item.from_version(v).model_copy(update={"annotations": annotations, "tags": ["ai", "ai/rag/hybrid", "aix"]})
    for each in (pending, v):
        storage.put_version(each)
    storage.put_item(item)

    storage.rename_tag("ai", "ml/ai")

    taxonomy = storage.get_taxonomy()
    assert [t.path for t in taxonomy.tags] == ["aix", "ml", "ml/ai", "ml/ai/rag", "ml/ai/rag/hybrid"]
    moved = taxonomy.get("ml/ai/rag")
    assert (moved.description, moved.created_in_taxonomy_version) == ("About ai/rag", 2)
    stored = storage.get_item(item.id)
    assert stored.tags == ["aix", "ml/ai", "ml/ai/rag/hybrid"]
    assert (stored.annotations.owner_tags, stored.annotations.rejected_tags) == (["ml/ai"], ["ml/ai/rag"])
    assert storage.get_version(v.id).enrichment.tags == ["aix", "ml/ai/rag/hybrid"]
    assert storage.get_version(pending.id).owner_tags == ["ml/ai/rag"]


def test_used_tags(storage):
    assert storage.used_tags() == set()
    pending = Version.create(
        CaptureRequest(url="https://example.com/p", channel=Channel.EXTENSION, tags=["picked"]), T1, "x"
    )
    v = version("https://example.com/a", T1).enriched(enrichment(["ai/rag"]))
    annotations = Annotations(owner_tags=["mine"], rejected_tags=["wrong"])
    for each in (pending, v):
        storage.put_version(each)
    storage.put_item(Item.from_version(v).model_copy(update={"annotations": annotations}))
    assert storage.used_tags() == {"picked", "ai/rag", "mine", "wrong"}


def test_ensure_indices_is_idempotent(storage):
    storage.ensure_indices()
    storage.ensure_indices()


def test_ensure_indices_adds_new_fields_to_existing_indices():
    client = opensearch_client()
    if client is None:
        pytest.skip(f"OpenSearch not reachable on {OPENSEARCH_URL}")
    store = OpenSearchStorage(client, index_prefix="test_upgrade_")
    old_items = copy.deepcopy(mappings.ITEMS)
    del old_items["mappings"]["properties"]["taxonomy_version"]
    client.indices.delete(index=store.items_index, ignore_unavailable=True)
    client.indices.create(index=store.items_index, body=old_items)
    try:
        store.ensure_indices()
        props = client.indices.get_mapping(index=store.items_index)[store.items_index]["mappings"]["properties"]
        assert props["taxonomy_version"] == {"type": "integer"}
    finally:
        for index in (store.items_index, store.versions_index, store.taxonomy_index):
            client.indices.delete(index=index, ignore_unavailable=True)
        delete_search_pipeline(store)


def thought(at: datetime, text: str = "An idea about soup.") -> Version:
    return Version.written(thought_id(at), at, ThoughtEdit(title="Soup", text=text))


def test_delete_version_removes_only_that_version(storage):
    a1, a2 = version("https://example.com/a", T1), version("https://example.com/a", T2)
    for v in (a1, a2):
        storage.put_version(v)
    storage.delete_version(a1.id)
    assert storage.list_versions(a1.item_id) == [a2]
    storage.delete_version("nope")  # unknown: nothing happens


def test_thought_version_round_trip(storage):
    v = thought(T1)
    storage.put_version(v)
    stored = storage.get_version(v.id)
    assert stored == v
    assert (stored.kind, stored.title, stored.text, stored.original_url) == (
        Kind.THOUGHT,
        "Soup",
        "An idea about soup.",
        None,
    )


def test_thought_item_round_trip(storage):
    v = thought(T1).enriched(enrichment(tags=["cooking"]))
    item = Item.rebuilt([v], Annotations(), T1)
    storage.put_item(item)
    assert storage.get_item(item.id) == item
    assert (item.media_type, item.text, item.tags, item.original_url) == (
        Kind.THOUGHT,
        "An idea about soup.",
        ["cooking"],
        None,
    )


def test_kind_filters_lists_and_search(storage):
    article = version("https://example.com/soup", T1).enriched(enrichment(tags=[]))
    storage.put_item(Item.from_version(article))
    storage.put_item(Item.rebuilt([thought(T2).enriched(enrichment(tags=[]))], Annotations(), T2))

    def kinds(items: list[Item]) -> list[Kind]:
        return [i.media_type for i in items]

    assert kinds(storage.list_items()) == [Kind.THOUGHT, Kind.ARTICLE]
    assert kinds(storage.list_items(kind=Kind.THOUGHT)) == [Kind.THOUGHT]
    assert kinds(storage.list_untagged_items(kind=Kind.ARTICLE)) == [Kind.ARTICLE]
    assert kinds(storage.search("soup", None, kind=Kind.THOUGHT)) == [Kind.THOUGHT]
    assert kinds(storage.search("soup", [0.5] * 1536, kind=Kind.ARTICLE)) == [Kind.ARTICLE]


def test_a_thoughts_text_is_keyword_searchable(storage):
    storage.put_item(Item.rebuilt([thought(T1, text="Lentils need no soaking.")], Annotations(), T1))
    assert [i.title for i in storage.search("lentils", None)] == ["Soup"]
