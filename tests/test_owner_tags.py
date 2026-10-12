from datetime import UTC, datetime

import pytest

from kb.models import Annotations, CaptureRequest, Channel, Enrichment, Item, Tag, Taxonomy, Version
from kb.owner_tags import allow_tag, tag_item, untag_item
from kb.pipeline.tag import merge
from kb.storage.memory import MemoryStorage
from kb.taxonomy import add_tag, retag_candidates

T1 = datetime(2026, 9, 21, 14, 0, 0, tzinfo=UTC)


def enriched(tags: list[str], url: str = "https://example.com/a", taxonomy_version: int = 1) -> Version:
    enrichment = Enrichment(
        title="T",
        summary="S",
        tags=tags,
        model="m",
        prompt_version="1",
        taxonomy_version=taxonomy_version,
        embedding_model="e",
    )
    return Version.create(CaptureRequest(url=url, channel=Channel.MANUAL), T1, "text").enriched(enrichment)


class TestMerge:
    def test_adds_without_removing(self):
        assert merge(["cooking"], ["ai"]) == ["ai", "cooking"]
        assert merge(["cooking"], []) == ["cooking"]

    def test_a_suggested_child_replaces_its_own_ancestors_only(self):
        assert merge(["ai", "cooking"], ["ai/retrieval/rag"]) == ["ai/retrieval/rag", "cooking"]
        assert merge(["ai/rag"], ["ai"]) == ["ai", "ai/rag"]  # a suggested parent never replaces a child
        assert merge(["aix"], ["ai/rag"]) == ["ai/rag", "aix"]  # same prefix, not an ancestor


class TestAnnotations:
    def test_item_tags_are_pipeline_plus_owner_minus_rejected(self):
        a = Annotations(owner_tags=["ai/agents"], rejected_tags=["cooking"])
        assert a.tags(["ai/rag", "cooking"]) == ["ai/agents", "ai/rag"]

    def test_adding_un_rejects_and_rejecting_un_adds(self):
        a = Annotations().rejecting("cooking").adding(["cooking"])
        assert (a.owner_tags, a.rejected_tags) == (["cooking"], [])
        a = a.rejecting("cooking")
        assert (a.owner_tags, a.rejected_tags) == ([], ["cooking"])
        assert a.allowing("cooking").rejected_tags == []


class TestRetagCandidates:
    @pytest.fixture
    def taxonomy(self):
        versions = {"ai": 1, "cooking": 2, "ai/rag": 3}
        return Taxonomy(tags=[Tag(path=p, created_at=T1, created_in_taxonomy_version=v) for p, v in versions.items()])

    def item(self, tags: list[str], taxonomy_version: int, url: str) -> Item:
        return Item.from_version(enriched(tags, url, taxonomy_version))

    def test_untagged_and_tagged_with_an_ancestor_of_a_new_tag(self, taxonomy):
        untagged = self.item([], 2, "https://example.com/u")
        parent = self.item(["ai"], 2, "https://example.com/p")
        unrelated = self.item(["cooking"], 2, "https://example.com/c")
        current = self.item([], 3, "https://example.com/n")  # already saw ai/rag and chose nothing
        assert retag_candidates([untagged, parent, unrelated, current], taxonomy) == [untagged.id, parent.id]


class TestOwnerTags:
    @pytest.fixture
    def storage(self):
        s = MemoryStorage()
        for path in ("ai", "ai/rag", "cooking"):
            add_tag(s, path)
        v = enriched(["ai/rag", "cooking"])
        s.put_version(v)
        s.put_item(Item.from_version(v))
        return s

    @pytest.fixture
    def iid(self, storage):
        return next(iter(storage.items))

    def test_untag_then_allow_again(self, storage, iid):
        item = untag_item(storage, iid, "cooking")
        assert (item.tags, item.annotations.rejected_tags) == (["ai/rag"], ["cooking"])
        assert storage.get_item(iid).tags == ["ai/rag"]

        item = allow_tag(storage, iid, "cooking")
        assert item.tags == ["ai/rag", "cooking"]  # the pipeline had chosen it, so it shows again
        assert item.annotations.rejected_tags == []

    def test_tag_by_hand(self, storage, iid):
        item = tag_item(storage, iid, "ai")
        assert (item.tags, item.annotations.owner_tags) == (["ai", "ai/rag", "cooking"], ["ai"])

    def test_tagging_a_rejected_tag_by_hand_un_rejects_it(self, storage, iid):
        untag_item(storage, iid, "cooking")
        item = tag_item(storage, iid, "cooking")
        assert (item.tags, item.annotations.rejected_tags) == (["ai/rag", "cooking"], [])

    @pytest.mark.parametrize(
        ("edit", "path", "message"),
        [
            (tag_item, "nope", "not in the taxonomy"),
            (untag_item, "ai", "not tagged"),
            (allow_tag, "ai", "not rejected"),
        ],
    )
    def test_invalid_edits(self, storage, iid, edit, path, message):
        with pytest.raises(ValueError, match=message):
            edit(storage, iid, path)

    def test_unknown_item_is_none(self, storage):
        assert tag_item(storage, "nope", "ai") is None
        assert untag_item(storage, "nope", "ai") is None
        assert allow_tag(storage, "nope", "ai") is None
