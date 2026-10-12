"""Hybrid search over Items: the query is matched by keywords and, via its embedding, by meaning."""

import logging

from pydantic import BaseModel

from kb.llm import LLM
from kb.models import DateRange, Kind, Match
from kb.storage import Storage

log = logging.getLogger(__name__)


class SearchResults(BaseModel):
    items: list[Match]
    semantic: bool  # False when the query could not be embedded and only keywords were matched


async def search(
    storage: Storage,
    llm: LLM,
    text: str,
    tag: str | None = None,
    saved: DateRange | None = None,
    kind: Kind | None = None,
) -> SearchResults:
    try:
        vector = await llm.embed(text)
    except Exception:
        log.exception("embedding the query failed; falling back to keyword search")
        vector = None
    return SearchResults(items=storage.search(text, vector, tag, saved, kind), semantic=vector is not None)
