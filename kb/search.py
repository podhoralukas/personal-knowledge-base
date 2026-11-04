"""Hybrid search over Items: the query is matched by keywords and, via its embedding, by meaning."""

import logging

from pydantic import BaseModel

from kb.llm import LLM
from kb.models import DateRange, Kind, Match, SessionSection
from kb.storage import Storage

log = logging.getLogger(__name__)


class SearchResults(BaseModel):
    items: list[Match]
    semantic: bool  # False when only keywords were matched: the query could not be embedded, or `section` was given


async def search(
    storage: Storage,
    llm: LLM,
    text: str,
    tag: str | None = None,
    saved: DateRange | None = None,
    kind: Kind | None = None,
    section: SessionSection | None = None,
) -> SearchResults:
    if section is not None:  # the embedding reads the whole summary, so meaning cannot be narrowed to one section
        return SearchResults(items=storage.search(text, None, tag, saved, kind, section), semantic=False)
    try:
        vector = await llm.embed(text)
    except Exception:
        log.exception("embedding the query failed; falling back to keyword search")
        vector = None
    return SearchResults(items=storage.search(text, vector, tag, saved, kind), semantic=vector is not None)
