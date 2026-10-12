"""Storage backed by OpenSearch."""

from opensearchpy import ConflictError, NotFoundError, OpenSearch
from opensearchpy.helpers import scan

from kb.config import (
    LIST_MAX_ITEMS,
    SEARCH_FIELDS,
    SEARCH_KNN_K,
    SEARCH_PIPELINE,
    SEARCH_RESULTS,
    TAXONOMY_MAX_TAGS,
    TAXONOMY_META_ID,
    Settings,
)
from kb.models import DateRange, Item, Kind, Match, Tag, Taxonomy, Version
from kb.storage import TagExists, mappings

ITEM_TAG_FIELDS = ("tags", "annotations.owner_tags", "annotations.rejected_tags")
VERSION_TAG_FIELDS = ("enrichment.tags", "owner_tags")

# Renames params.old to params.new (and its sub-tags) in every tag list of an Item or Version document.
RENAME_SCRIPT = """
List moved(List paths, String old, String renamed) {
  List out = new ArrayList();
  for (String p : paths) {
    out.add(p == old || p.startsWith(old + '/') ? renamed + p.substring(old.length()) : p);
  }
  Collections.sort(out);
  return out;
}
def s = ctx._source;
for (String f : ['tags', 'owner_tags']) {
  if (s[f] != null) { s[f] = moved(s[f], params.old, params.new); }
}
for (String parent : ['annotations', 'enrichment']) {
  if (s[parent] != null) {
    for (String f : ['tags', 'owner_tags', 'rejected_tags']) {
      if (s[parent][f] != null) { s[parent][f] = moved(s[parent][f], params.old, params.new); }
    }
  }
}
"""


class OpenSearchStorage:
    def __init__(self, client: OpenSearch, index_prefix: str = "") -> None:
        self.client = client
        self.items_index = f"{index_prefix}items"
        self.versions_index = f"{index_prefix}versions"
        self.taxonomy_index = f"{index_prefix}taxonomy"
        self.search_pipeline = f"{index_prefix}{SEARCH_PIPELINE}"

    @classmethod
    def from_settings(cls, settings: Settings) -> "OpenSearchStorage":
        auth = (settings.opensearch_username, settings.opensearch_password)
        client = OpenSearch(
            hosts=[settings.opensearch_url],
            http_auth=auth if all(auth) else None,
            use_ssl=settings.opensearch_url.startswith("https"),
            verify_certs=False,
            ssl_show_warn=False,
        )
        return cls(client, settings.opensearch_index_prefix)

    def ensure_indices(self) -> None:
        for index, body in (
            (self.items_index, mappings.ITEMS),
            (self.versions_index, mappings.VERSIONS),
            (self.taxonomy_index, mappings.TAXONOMY),
        ):
            if self.client.indices.exists(index=index):
                self.client.indices.put_mapping(index=index, body=body["mappings"])  # adds new fields
            else:
                self.client.indices.create(index=index, body=body)
        self.client.transport.perform_request(
            "PUT", f"/_search/pipeline/{self.search_pipeline}", body=mappings.SEARCH_PIPELINE
        )

    def put_version(self, version: Version) -> None:
        self.client.index(
            index=self.versions_index,
            id=version.id,
            body=version.model_dump(mode="json", exclude_none=True),
            refresh=True,
        )

    def get_version(self, version_id: str) -> Version | None:
        return self._get(self.versions_index, version_id, Version)

    def delete_version(self, version_id: str) -> None:
        try:
            self.client.delete(index=self.versions_index, id=version_id, refresh=True)
        except NotFoundError:
            pass

    def list_versions(self, item_id: str) -> list[Version]:
        body = {"query": {"term": {"item_id": item_id}}, "sort": [{"captured_at": "desc"}], "size": 1000}
        hits = self.client.search(index=self.versions_index, body=body)["hits"]["hits"]
        return [Version.model_validate(h["_source"]) for h in hits]

    def put_item(self, item: Item) -> None:
        self.client.index(
            index=self.items_index, id=item.id, body=item.model_dump(mode="json", exclude_none=True), refresh=True
        )

    def get_item(self, item_id: str) -> Item | None:
        return self._get(self.items_index, item_id, Item)

    def delete_item(self, item_id: str) -> bool:
        versions = self.client.delete_by_query(
            index=self.versions_index,
            body={"query": {"term": {"item_id": item_id}}},
            params={"refresh": "true", "conflicts": "proceed"},
        )
        try:
            self.client.delete(index=self.items_index, id=item_id, refresh=True)
        except NotFoundError:
            return versions["deleted"] > 0
        return True

    def list_item_ids(self) -> list[str]:
        hits = scan(self.client, index=self.items_index, query={"query": {"match_all": {}}, "_source": False})
        return [h["_id"] for h in hits]

    def list_items_tagged_before(self, taxonomy_version: int) -> list[Item]:
        query = {
            "query": {"range": {"taxonomy_version": {"lt": taxonomy_version}}},
            "_source": {"excludes": ["embedding"]},
        }
        return [Item.model_validate(h["_source"]) for h in scan(self.client, index=self.items_index, query=query)]

    def list_items(
        self, tag: str | None = None, saved: DateRange | None = None, kind: Kind | None = None
    ) -> list[Item]:
        return self._newest_items(filters(tag, saved, kind))

    def search(
        self,
        text: str,
        vector: list[float] | None,
        tag: str | None = None,
        saved: DateRange | None = None,
        kind: Kind | None = None,
    ) -> list[Match]:
        keyword = {"multi_match": {"query": text, "fields": SEARCH_FIELDS}}
        knn = {"vector": vector, "k": SEARCH_KNN_K}
        narrowed = filters(tag, saved, kind)
        if narrowed != {"match_all": {}}:
            keyword = {"bool": {"must": keyword, "filter": narrowed}}
            knn["filter"] = narrowed
        query = keyword if vector is None else {"hybrid": {"queries": [keyword, {"knn": {"embedding": knn}}]}}
        body = {"query": query, "size": SEARCH_RESULTS, "_source": {"excludes": ["embedding"]}}
        response = self.client.search(
            index=self.items_index, body=body, params={"search_pipeline": self.search_pipeline}
        )
        return [Match.model_validate(h["_source"] | {"score": h["_score"]}) for h in response["hits"]["hits"]]

    def count_items(self, tags: list[str]) -> dict[str, int]:
        if not tags:
            return {}
        body = {"size": 0, "aggs": {"tags": {"filters": {"filters": {t: tag_subtree(t) for t in tags}}}}}
        buckets = self.client.search(index=self.items_index, body=body)["aggregations"]["tags"]["buckets"]
        return {t: bucket["doc_count"] for t, bucket in buckets.items()}

    def list_untagged_items(self, saved: DateRange | None = None, kind: Kind | None = None) -> list[Item]:
        return self._newest_items(filters(None, saved, kind, untagged=True))

    def _newest_items(self, query: dict) -> list[Item]:
        body = {
            "query": query,
            "sort": [{"first_captured_at": "desc"}],
            "size": LIST_MAX_ITEMS,
            "_source": {"excludes": ["embedding"]},
        }
        hits = self.client.search(index=self.items_index, body=body)["hits"]["hits"]
        return [Item.model_validate(h["_source"]) for h in hits]

    def get_taxonomy(self) -> Taxonomy:
        body = {"query": {"exists": {"field": "path"}}, "sort": [{"path": "asc"}], "size": TAXONOMY_MAX_TAGS}
        hits = self.client.search(index=self.taxonomy_index, body=body)["hits"]["hits"]
        return Taxonomy(tags=[Tag.model_validate(h["_source"]) for h in hits])

    def next_taxonomy_version(self) -> int:
        response = self.client.update(
            index=self.taxonomy_index,
            id=TAXONOMY_META_ID,
            body={
                "script": {"source": "ctx._source.taxonomy_version += 1", "lang": "painless"},
                "upsert": {"taxonomy_version": 1},
            },
            params={"retry_on_conflict": 5, "_source": "true", "refresh": "true"},
        )
        return response["get"]["_source"]["taxonomy_version"]

    def put_tag(self, tag: Tag) -> None:
        try:
            self.client.index(
                index=self.taxonomy_index,
                id=tag.path,
                body=tag.model_dump(mode="json"),
                op_type="create",
                refresh=True,
            )
        except ConflictError:
            raise TagExists(tag.path)

    def update_tag(self, tag: Tag) -> None:
        self.client.index(index=self.taxonomy_index, id=tag.path, body=tag.model_dump(mode="json"), refresh=True)

    def delete_tag(self, path: str) -> None:
        self.client.delete(index=self.taxonomy_index, id=path, refresh=True)

    def rename_tag(self, old: str, new: str) -> None:
        for tag in self.get_taxonomy().tags:
            if tag.path == old or tag.path.startswith(f"{old}/"):
                moved = tag.model_copy(update={"path": new + tag.path[len(old) :]})
                self.client.index(index=self.taxonomy_index, id=moved.path, body=moved.model_dump(mode="json"))
                self.client.delete(index=self.taxonomy_index, id=tag.path)
        self.client.indices.refresh(index=self.taxonomy_index)

        script = {"source": RENAME_SCRIPT, "lang": "painless", "params": {"old": old, "new": new}}
        for index, fields in ((self.items_index, ITEM_TAG_FIELDS), (self.versions_index, VERSION_TAG_FIELDS)):
            matches = [q for f in fields for q in ({"term": {f: old}}, {"prefix": {f: f"{old}/"}})]
            self.client.update_by_query(
                index=index,
                body={"query": {"bool": {"should": matches, "minimum_should_match": 1}}, "script": script},
                params={"refresh": "true", "conflicts": "proceed"},
            )

    def used_tags(self) -> set[str]:
        used = set()
        for index, fields in ((self.items_index, ITEM_TAG_FIELDS), (self.versions_index, VERSION_TAG_FIELDS)):
            aggs = {f: {"terms": {"field": f, "size": TAXONOMY_MAX_TAGS}} for f in fields}
            response = self.client.search(index=index, body={"size": 0, "aggs": aggs})
            used |= {b["key"] for agg in response["aggregations"].values() for b in agg["buckets"]}
        return used

    def _get[T: (Item, Version)](self, index: str, doc_id: str, model: type[T]) -> T | None:
        try:
            doc = self.client.get(index=index, id=doc_id)
        except NotFoundError:
            return None
        return model.model_validate(doc["_source"])


def filters(tag: str | None, saved: DateRange | None, kind: Kind | None = None, untagged: bool = False) -> dict:
    """One query for the tag subtree, the saved-date range, the Kind and/or untagged Items; match_all without any."""
    clauses = []
    if tag is not None:
        clauses.append(tag_subtree(tag))
    if kind is not None:
        clauses.append({"term": {"media_type": kind.value}})
    if saved is not None and (saved.lower or saved.upper):
        bounds = {"gte": saved.lower, "lt": saved.upper}
        clauses.append({"range": {"first_captured_at": {k: v.isoformat() for k, v in bounds.items() if v}}})
    if not clauses and not untagged:
        return {"match_all": {}}
    query = {"bool": {"filter": clauses}}
    if untagged:
        query["bool"]["must_not"] = {"exists": {"field": "tags"}}
    return query


def tag_subtree(tag: str) -> dict:
    """Matches Items carrying `tag` or any of its sub-tags."""
    return {"bool": {"should": [{"term": {"tags": tag}}, {"prefix": {"tags": f"{tag}/"}}], "minimum_should_match": 1}}
