"""Storage seam: the pipeline and the app talk to `Storage`, never to OpenSearch directly."""

from typing import Protocol

from kb.models import DateRange, Item, Kind, Match, Tag, Taxonomy, Version


class Storage(Protocol):
    def ensure_indices(self) -> None: ...

    def put_version(self, version: Version) -> None: ...

    def get_version(self, version_id: str) -> Version | None: ...

    def delete_version(self, version_id: str) -> None: ...

    def list_versions(self, item_id: str) -> list[Version]:
        """Newest first."""
        ...

    def put_item(self, item: Item) -> None: ...

    def get_item(self, item_id: str) -> Item | None: ...

    def delete_item(self, item_id: str) -> bool:
        """Delete the Item and all its Versions; False if there was nothing to delete."""
        ...

    def list_item_ids(self) -> list[str]: ...

    def list_items_tagged_before(self, taxonomy_version: int) -> list[Item]:
        """Every Item tagged against an older taxonomy version, without embeddings."""
        ...

    def list_items(
        self, tag: str | None = None, saved: DateRange | None = None, kind: Kind | None = None
    ) -> list[Item]:
        """Newest saved first, without embeddings; `tag` also matches its sub-tags."""
        ...

    def search(
        self,
        text: str,
        vector: list[float] | None,
        tag: str | None = None,
        saved: DateRange | None = None,
        kind: Kind | None = None,
    ) -> list[Match]:
        """Best match first, without embeddings. Keyword-only when `vector` is None."""
        ...

    def count_items(self, tags: list[str]) -> dict[str, int]:
        """Items under each tag, sub-tags included."""
        ...

    def list_untagged_items(self, saved: DateRange | None = None, kind: Kind | None = None) -> list[Item]:
        """Newest saved first, without embeddings."""
        ...

    def get_taxonomy(self) -> Taxonomy: ...

    def next_taxonomy_version(self) -> int:
        """Atomically increment the taxonomy version counter and return the new value."""
        ...

    def put_tag(self, tag: Tag) -> None:
        """Raises TagExists if the path is already taken."""
        ...

    def update_tag(self, tag: Tag) -> None:
        """Overwrite an existing Tag, e.g. with a new description."""
        ...

    def delete_tag(self, path: str) -> None: ...

    def rename_tag(self, old: str, new: str) -> None:
        """Rename the Tag and its sub-tags everywhere: Taxonomy, Items, Annotations and Versions."""
        ...

    def used_tags(self) -> set[str]:
        """Every Tag path carried by any Item, Annotation or Version."""
        ...


class TagExists(ValueError):
    pass
