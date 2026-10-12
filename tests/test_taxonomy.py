from datetime import UTC, datetime

import pytest

from kb.models import Tag, Taxonomy
from kb.storage import TagExists
from kb.storage.memory import MemoryStorage
from kb.taxonomy import TagNotFound, add_tag, deletable_tags, delete_tag, describe_tag, rename_tag


@pytest.fixture
def storage():
    return MemoryStorage()


def test_tag_parent_and_name():
    tag = Tag(path="ai/retrieval/rag", created_at="2026-10-02T10:00:00Z", created_in_taxonomy_version=1)
    assert (tag.parent, tag.name) == ("ai/retrieval", "rag")
    root = tag.model_copy(update={"path": "ai"})
    assert (root.parent, root.name) == (None, "ai")


def test_add_root_and_child_tags(storage):
    ai = add_tag(storage, "ai", "  Artificial intelligence ")
    rag = add_tag(storage, "ai/rag")
    assert (ai.created_in_taxonomy_version, rag.created_in_taxonomy_version) == (1, 2)
    assert ai.description == "Artificial intelligence"
    taxonomy = storage.get_taxonomy()
    assert [t.path for t in taxonomy.tags] == ["ai", "ai/rag"]
    assert taxonomy.version == 2


def test_child_needs_existing_parent(storage):
    with pytest.raises(ValueError, match="parent tag 'ai' does not exist"):
        add_tag(storage, "ai/rag")
    assert storage.get_taxonomy() == Taxonomy()


def test_duplicate_tag_is_rejected_without_bumping_the_version(storage):
    add_tag(storage, "ai")
    with pytest.raises(TagExists):
        add_tag(storage, "ai")
    assert storage.get_taxonomy().version == 1
    assert storage.taxonomy_version == 1


@pytest.mark.parametrize("path", ["", "AI", "ai/", "/ai", "ai//rag", "ai rag", "ai_rag", "-ai", "ai-", "ai/rag?"])
def test_invalid_paths_are_rejected(storage, path):
    with pytest.raises(ValueError, match="invalid tag path"):
        add_tag(storage, path)


def test_slug_segments_with_digits_and_hyphens_are_valid(storage):
    add_tag(storage, "web3")
    assert add_tag(storage, "web3/zk-rollups").path == "web3/zk-rollups"


@pytest.fixture
def tree(storage):
    for path in ("ai", "ai/reserach", "ai/reserach/papers", "news"):
        add_tag(storage, path)
    return storage


def test_describe_tag(tree):
    assert describe_tag(tree, "news", "  General news ").description == "General news"
    assert tree.get_taxonomy().get("news").description == "General news"
    with pytest.raises(TagNotFound):
        describe_tag(tree, "nope", "x")


def test_rename_fixes_spelling_with_sub_tags(tree):
    renamed = rename_tag(tree, "ai/reserach", "ai/research")
    assert (renamed.path, renamed.created_in_taxonomy_version) == ("ai/research", 2)
    assert [t.path for t in tree.get_taxonomy().tags] == ["ai", "ai/research", "ai/research/papers", "news"]


def test_rename_moves_to_another_parent(tree):
    rename_tag(tree, "ai/reserach", "research")
    assert [t.path for t in tree.get_taxonomy().tags] == ["ai", "news", "research", "research/papers"]


@pytest.mark.parametrize(
    ("new_path", "error", "message"),
    [
        ("news", TagExists, "news"),
        ("Bad Path", ValueError, "invalid tag path"),
        ("science/research", ValueError, "parent tag 'science' does not exist"),
        ("ai/reserach/papers/x", ValueError, "itself or one of its sub-tags"),
        ("ai/reserach", ValueError, "itself"),
    ],
)
def test_rename_errors(tree, new_path, error, message):
    with pytest.raises(error, match=message):
        rename_tag(tree, "ai/reserach", new_path)


def test_rename_unknown_tag(tree):
    with pytest.raises(TagNotFound):
        rename_tag(tree, "nope", "other")


def test_delete_only_unused_leaf_tags(tree):
    from kb.models import Annotations, CaptureRequest, Channel, Enrichment, Item, Version

    v = Version.create(
        CaptureRequest(url="https://example.com/a", channel=Channel.MANUAL), datetime(2026, 10, 5, tzinfo=UTC), "x"
    )
    v = v.enriched(
        Enrichment(title="T", summary="S", model="m", prompt_version="1", taxonomy_version=4, embedding_model="e")
    )
    tree.put_version(v)
    tree.put_item(Item.from_version(v).model_copy(update={"annotations": Annotations(rejected_tags=["news"])}))
    assert deletable_tags(tree) == {"ai/reserach/papers"}

    with pytest.raises(ValueError, match="has sub-tags"):
        delete_tag(tree, "ai")
    with pytest.raises(ValueError, match="used by items"):
        delete_tag(tree, "news")  # even a rejected tag counts as used
    delete_tag(tree, "ai/reserach/papers")
    assert tree.get_taxonomy().get("ai/reserach/papers") is None
    with pytest.raises(TagNotFound):
        delete_tag(tree, "ai/reserach/papers")
