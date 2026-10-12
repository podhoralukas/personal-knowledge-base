"""The Owner's tag corrections on one Item: add a Tag by hand, untag, allow a rejected Tag again."""

from kb.models import Annotations, Item
from kb.storage import Storage


def tag_item(storage: Storage, item_id: str, path: str) -> Item | None:
    """None for an unknown Item; ValueError for a Tag not in the Taxonomy."""
    item = storage.get_item(item_id)
    if item is None:
        return None
    if storage.get_taxonomy().get(path) is None:
        raise ValueError(f"tag {path!r} is not in the taxonomy")
    return _save(storage, item, item.annotations.adding([path]))


def untag_item(storage: Storage, item_id: str, path: str) -> Item | None:
    """None for an unknown Item; ValueError when the Item does not carry the Tag."""
    item = storage.get_item(item_id)
    if item is None:
        return None
    if path not in item.tags:
        raise ValueError(f"the item is not tagged {path!r}")
    return _save(storage, item, item.annotations.rejecting(path))


def allow_tag(storage: Storage, item_id: str, path: str) -> Item | None:
    """None for an unknown Item; ValueError when the Tag is not rejected for it."""
    item = storage.get_item(item_id)
    if item is None:
        return None
    if path not in item.annotations.rejected_tags:
        raise ValueError(f"tag {path!r} is not rejected for this item")
    return _save(storage, item, item.annotations.allowing(path))


def _save(storage: Storage, item: Item, annotations: Annotations) -> Item:
    updated = item.annotated(annotations, _pipeline_tags(storage, item))
    storage.put_item(updated)
    return updated


def _pipeline_tags(storage: Storage, item: Item) -> list[str]:
    """From the current Version, or the newest enriched one while a Thought's edit is pending or failed."""
    current = storage.get_version(item.current_version_id)
    if current.enrichment is not None:
        return current.enrichment.tags
    return next((v.enrichment.tags for v in storage.list_versions(item.id) if v.enrichment), [])
