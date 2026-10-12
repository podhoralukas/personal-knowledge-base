"""Tag step: one structured LLM call that chooses Tags for a summary from the current Taxonomy."""

import logging

from pydantic import BaseModel, Field

from kb.llm import LLM
from kb.models import Taxonomy

log = logging.getLogger(__name__)

PROMPT_VERSION = "1"

SYSTEM_PROMPT = """You are tagging an entry of a personal knowledge base against a fixed taxonomy.
Return the paths of the tags that describe what the entry is substantially about.
- Use only paths exactly as listed below; never invent or modify a path.
- Prefer the most specific fitting tag; use a parent tag only when none of its children fits.
- An empty list is a valid answer when no tag fits well.

Taxonomy (path: description):
{taxonomy}"""


class Tagging(BaseModel):
    tags: list[str] = Field(default_factory=list)


async def tag(llm: LLM, taxonomy: Taxonomy, title: str, text: str) -> list[str]:
    """Sorted Tag paths; unknown paths from the model are dropped. No LLM call for an empty Taxonomy."""
    if not taxonomy.tags:
        return []
    listing = "\n".join(f"- {t.path}: {t.description}" if t.description else f"- {t.path}" for t in taxonomy.tags)
    entry = f"# {title}\n\n{text}"
    answer = await llm.structured(SYSTEM_PROMPT.format(taxonomy=listing), entry, Tagging)

    known = {t.path for t in taxonomy.tags}
    unknown = set(answer.tags) - known
    if unknown:
        log.warning("dropping tags not in the taxonomy: %s", sorted(unknown))
    return sorted(set(answer.tags) & known)


def merge(old: list[str], suggested: list[str]) -> list[str]:
    """Re-tags only add; a suggested Tag replaces only its own ancestors (ai + ai/rag -> ai/rag)."""
    union = set(old) | set(suggested)
    return sorted(t for t in union if not any(s.startswith(f"{t}/") for s in suggested))
