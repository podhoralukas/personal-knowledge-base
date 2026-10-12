"""Editing the Taxonomy: Tags are added under an existing parent, described, renamed or moved (spelling and
position, never meaning), and deleted only while nothing uses them."""

import re
from datetime import UTC, datetime

from kb.config import TAG_PATH_PATTERN
from kb.models import Item, Tag, Taxonomy
from kb.storage import Storage, TagExists


class TagNotFound(LookupError):
    pass


def add_tag(storage: Storage, path: str, description: str = "") -> Tag:
    """Raises ValueError for an invalid path, a missing parent or an existing tag."""
    _check_new_path(storage.get_taxonomy(), path)

    tag = Tag(
        path=path,
        description=description.strip(),
        created_at=datetime.now(UTC),
        created_in_taxonomy_version=storage.next_taxonomy_version(),
    )
    storage.put_tag(tag)
    return tag


def describe_tag(storage: Storage, path: str, description: str) -> Tag:
    tag = _existing(storage.get_taxonomy(), path).model_copy(update={"description": description.strip()})
    storage.update_tag(tag)
    return tag


def rename_tag(storage: Storage, path: str, new_path: str) -> Tag:
    """Rename or move the Tag with its sub-tags, everywhere it appears. Raises TagNotFound, TagExists or ValueError."""
    taxonomy = storage.get_taxonomy()
    _existing(taxonomy, path)
    if new_path == path or new_path.startswith(f"{path}/"):
        raise ValueError(f"{new_path!r} is {path!r} itself or one of its sub-tags")
    _check_new_path(taxonomy, new_path)
    storage.rename_tag(path, new_path)
    return storage.get_taxonomy().get(new_path)


def delete_tag(storage: Storage, path: str) -> None:
    """Only a Tag nothing uses: no sub-tags, and no Item, Annotation or Version carries it."""
    taxonomy = storage.get_taxonomy()
    _existing(taxonomy, path)
    if any(t.parent == path for t in taxonomy.tags):
        raise ValueError(f"tag {path!r} has sub-tags")
    if path in storage.used_tags():
        raise ValueError(f"tag {path!r} is used by items; untag them first")
    storage.delete_tag(path)


def deletable_tags(storage: Storage) -> set[str]:
    taxonomy = storage.get_taxonomy()
    parents = {t.parent for t in taxonomy.tags}
    return {t.path for t in taxonomy.tags} - parents - storage.used_tags()


def _existing(taxonomy: Taxonomy, path: str) -> Tag:
    tag = taxonomy.get(path)
    if tag is None:
        raise TagNotFound(path)
    return tag


def _check_new_path(taxonomy: Taxonomy, path: str) -> None:
    if not re.fullmatch(TAG_PATH_PATTERN, path):
        raise ValueError(f"invalid tag path {path!r}: use lowercase slugs joined by '/', e.g. ai/retrieval/rag")
    if taxonomy.get(path) is not None:
        raise TagExists(path)
    parent = path.rpartition("/")[0]
    if parent and taxonomy.get(parent) is None:
        raise ValueError(f"parent tag {parent!r} does not exist")


def retag_targets(storage: Storage, every_item: bool = False) -> list[str]:
    """Item ids a re-tag should reach: by default only those a newly added Tag could change."""
    if every_item:
        return storage.list_item_ids()
    taxonomy = storage.get_taxonomy()
    return retag_candidates(storage.list_items_tagged_before(taxonomy.version), taxonomy)


def retag_candidates(items: list[Item], taxonomy: Taxonomy) -> list[str]:
    """Untagged Items, and Items tagged with an ancestor of a Tag added since they were tagged."""
    ids = []
    for item in items:
        added = [t.path for t in taxonomy.tags if t.created_in_taxonomy_version > item.taxonomy_version]
        if added and (not item.tags or any(a.startswith(f"{t}/") for t in item.tags for a in added)):
            ids.append(item.id)
    return ids
