"""OpenSearch index definitions for `items`, `versions` and `taxonomy`. Strict: every stored field is listed here."""

from kb.config import EMBEDDING_DIM, SEARCH_KEYWORD_WEIGHT, SEARCH_VECTOR_WEIGHT

_KNN_SETTINGS = {"index": {"knn": True}}
_EMBEDDING = {
    "type": "knn_vector",
    "dimension": EMBEDDING_DIM,
    "method": {"name": "hnsw", "space_type": "cosinesimil", "engine": "lucene"},
}
_ENRICHMENT = {
    "properties": {
        "title": {"type": "text"},
        "summary": {"type": "text"},
        "key_points": {"type": "text"},
        "published_date": {"type": "date", "ignore_malformed": True},
        "language": {"type": "keyword"},
        "tags": {"type": "keyword"},
        "embedding": _EMBEDDING,
        "model": {"type": "keyword"},
        "prompt_version": {"type": "keyword"},
        "taxonomy_version": {"type": "integer"},
        "embedding_model": {"type": "keyword"},
        "tag_model": {"type": "keyword"},
        "tag_prompt_version": {"type": "keyword"},
        "reused_from": {"type": "keyword"},
    }
}

VERSIONS = {
    "settings": _KNN_SETTINGS,
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "id": {"type": "keyword"},
            "item_id": {"type": "keyword"},
            "captured_at": {"type": "date"},
            "channel": {"type": "keyword"},
            "kind": {"type": "keyword"},
            "original_url": {"type": "keyword"},
            "title": {"type": "text", "index": False},
            "text": {"type": "text", "index": False},
            "content_hash": {"type": "keyword"},
            "content": {"type": "text", "index": False},
            "status": {"type": "keyword"},
            "enrichment": _ENRICHMENT,
            "error": {"type": "text", "index": False},
            "owner_tags": {"type": "keyword"},
            "note": {"type": "text", "index": False},
        },
    },
}

ITEMS = {
    "settings": _KNN_SETTINGS,
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "id": {"type": "keyword"},
            "normalised_url": {"type": "keyword"},
            "original_url": {"type": "keyword"},
            "media_type": {"type": "keyword"},
            "first_captured_at": {"type": "date"},
            "captured_at": {"type": "date"},
            "current_version_id": {"type": "keyword"},
            "title": {"type": "text"},
            "summary": {"type": "text"},
            "key_points": {"type": "text"},
            "text": {"type": "text"},
            "tags": {"type": "keyword"},
            "taxonomy_version": {"type": "integer"},
            "embedding": _EMBEDDING,
            "annotations": {
                "properties": {
                    "notes": {"type": "text"},
                    "owner_tags": {"type": "keyword"},
                    "rejected_tags": {"type": "keyword"},
                }
            },
        },
    },
}

# Normalises BM25 and k-NN scores of a hybrid query to 0..1 and averages them.
SEARCH_PIPELINE = {
    "description": "kb hybrid search: min-max normalised BM25 + k-NN, weighted arithmetic mean",
    "phase_results_processors": [
        {
            "normalization-processor": {
                "normalization": {"technique": "min_max"},
                "combination": {
                    "technique": "arithmetic_mean",
                    "parameters": {"weights": [SEARCH_KEYWORD_WEIGHT, SEARCH_VECTOR_WEIGHT]},
                },
            }
        }
    ],
}

# Tag documents (_id = path) plus one counter document holding `taxonomy_version`.
TAXONOMY = {
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "path": {"type": "keyword"},
            "description": {"type": "text"},
            "created_at": {"type": "date"},
            "created_in_taxonomy_version": {"type": "integer"},
            "taxonomy_version": {"type": "integer"},
        },
    },
}
