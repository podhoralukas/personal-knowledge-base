"""In-memory Storage for tests."""

import math
import re
from collections.abc import Iterable

from kb.config import LIST_MAX_ITEMS, SEARCH_KEYWORD_WEIGHT, SEARCH_KNN_K, SEARCH_RESULTS, SEARCH_VECTOR_WEIGHT
from kb.models import DateRange, Item, Kind, Match, Tag, Taxonomy, Version
from kb.storage import TagExists


class MemoryStorage:
    def __init__(self) -> None:
        self.versions: dict[str, Version] = {}
        self.items: dict[str, Item] = {}
        self.tags: dict[str, Tag] = {}
        self.taxonomy_version = 0

    def ensure_indices(self) -> None:
        pass

    def put_version(self, version: Version) -> None:
        self.versions[version.id] = version

    def get_version(self, version_id: str) -> Version | None:
        return self.versions.get(version_id)

    def delete_version(self, version_id: str) -> None:
        self.versions.pop(version_id, None)

    def list_versions(self, item_id: str) -> list[Version]:
        matching = [v for v in self.versions.values() if v.item_id == item_id]
        return sorted(matching, key=lambda v: v.captured_at, reverse=True)

    def put_item(self, item: Item) -> None:
        self.items[item.id] = item

    def get_item(self, item_id: str) -> Item | None:
        return self.items.get(item_id)

    def delete_item(self, item_id: str) -> bool:
        version_ids = [v.id for v in self.versions.values() if v.item_id == item_id]
        for version_id in version_ids:
            del self.versions[version_id]
        return self.items.pop(item_id, None) is not None or bool(version_ids)

    def list_item_ids(self) -> list[str]:
        return list(self.items)

    def list_items_tagged_before(self, taxonomy_version: int) -> list[Item]:
        older = (i for i in self.items.values() if i.taxonomy_version < taxonomy_version)
        return [i.model_copy(update={"embedding": None}) for i in older]

    def list_items(
        self, tag: str | None = None, saved: DateRange | None = None, kind: Kind | None = None
    ) -> list[Item]:
        return self._newest_first(i for i in self._filtered(saved, kind) if tag is None or has_tag(i, tag))

    def count_items(self, tags: list[str]) -> dict[str, int]:
        return {t: sum(has_tag(i, t) for i in self.items.values()) for t in tags}

    def list_untagged_items(self, saved: DateRange | None = None, kind: Kind | None = None) -> list[Item]:
        return self._newest_first(i for i in self._filtered(saved, kind) if not i.tags)

    def search(
        self,
        text: str,
        vector: list[float] | None,
        tag: str | None = None,
        saved: DateRange | None = None,
        kind: Kind | None = None,
    ) -> list[Match]:
        """Term overlap stands in for BM25; scores are combined the way the OpenSearch pipeline does it."""
        candidates = [i for i in self._filtered(saved, kind) if tag is None or has_tag(i, tag)]
        keyword = {i.id: s for i in candidates if (s := term_score(text, i)) > 0}
        semantic = {}
        if vector is not None:
            nearest = sorted(
                ((i.id, cosine(vector, i.embedding)) for i in candidates if i.embedding), key=lambda p: -p[1]
            )
            semantic = dict(nearest[:SEARCH_KNN_K])
        keyword, semantic = min_max(keyword), min_max(semantic)
        weights = (1.0, 0.0) if vector is None else (SEARCH_KEYWORD_WEIGHT, SEARCH_VECTOR_WEIGHT)
        combined = {
            iid: weights[0] * keyword.get(iid, 0) + weights[1] * semantic.get(iid, 0) for iid in keyword | semantic
        }
        ranked = sorted(combined, key=lambda iid: -combined[iid])[:SEARCH_RESULTS]
        return [Match(**self.items[iid].model_dump(exclude={"embedding"}), score=combined[iid]) for iid in ranked]

    def _filtered(self, saved: DateRange | None, kind: Kind | None) -> list[Item]:
        return [
            i
            for i in self.items.values()
            if (saved is None or saved.contains(i.first_captured_at)) and (kind is None or i.media_type is kind)
        ]

    @staticmethod
    def _newest_first(items: Iterable[Item]) -> list[Item]:
        stripped = [i.model_copy(update={"embedding": None}) for i in items]
        return sorted(stripped, key=lambda i: i.first_captured_at, reverse=True)[:LIST_MAX_ITEMS]

    def get_taxonomy(self) -> Taxonomy:
        return Taxonomy(tags=sorted(self.tags.values(), key=lambda t: t.path))

    def next_taxonomy_version(self) -> int:
        self.taxonomy_version += 1
        return self.taxonomy_version

    def put_tag(self, tag: Tag) -> None:
        if tag.path in self.tags:
            raise TagExists(tag.path)
        self.tags[tag.path] = tag

    def update_tag(self, tag: Tag) -> None:
        self.tags[tag.path] = tag

    def delete_tag(self, path: str) -> None:
        del self.tags[path]

    def rename_tag(self, old: str, new: str) -> None:
        def move(paths: list[str]) -> list[str]:
            return sorted(renamed(p, old, new) for p in paths)

        self.tags = {
            renamed(p, old, new): t.model_copy(update={"path": renamed(p, old, new)}) for p, t in self.tags.items()
        }
        for iid, i in self.items.items():
            a = i.annotations
            annotations = a.model_copy(
                update={"owner_tags": move(a.owner_tags), "rejected_tags": move(a.rejected_tags)}
            )
            self.items[iid] = i.model_copy(update={"tags": move(i.tags), "annotations": annotations})
        for vid, v in self.versions.items():
            update = {"owner_tags": move(v.owner_tags)}
            if v.enrichment is not None:
                update["enrichment"] = v.enrichment.model_copy(update={"tags": move(v.enrichment.tags)})
            self.versions[vid] = v.model_copy(update=update)

    def used_tags(self) -> set[str]:
        used = set()
        for i in self.items.values():
            used |= {*i.tags, *i.annotations.owner_tags, *i.annotations.rejected_tags}
        for v in self.versions.values():
            used |= {*v.owner_tags, *(v.enrichment.tags if v.enrichment else [])}
        return used


def renamed(path: str, old: str, new: str) -> str:
    """`path` after renaming `old` to `new`: the Tag itself and its sub-tags move, anything else stays."""
    if path == old or path.startswith(f"{old}/"):
        return new + path[len(old) :]
    return path


def has_tag(item: Item, tag: str) -> bool:
    return any(t == tag or t.startswith(f"{tag}/") for t in item.tags)


def term_score(text: str, item: Item) -> float:
    terms = set(re.findall(r"\w+", text.lower()))
    fields = (
        (item.title, 2.0),
        (item.summary, 1.0),
        (" ".join(item.key_points), 1.0),
        (item.text or "", 1.0),
        (item.annotations.notes, 1.0),
    )
    return sum(weight * len(terms & set(re.findall(r"\w+", field.lower()))) for field, weight in fields)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norms = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return (1 + dot / norms) / 2 if norms else 0.0


def min_max(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    return {k: (v - low) / (high - low) if high > low else 1.0 for k, v in scores.items()}
