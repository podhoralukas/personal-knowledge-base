"""Summarise step: one structured LLM call over the fetched markdown."""

from datetime import date

from pydantic import BaseModel, Field

from kb.config import SUMMARY_INPUT_MAX_CHARS
from kb.llm import LLM

PROMPT_VERSION = "1"

SYSTEM_PROMPT = """You are indexing a web page for a personal knowledge base.
Read the page content (markdown) and return:
- title: the article's own title, cleaned of site name and boilerplate
- summary: 3-6 sentences on what the page says, factual, no marketing language
- key_points: the 3-8 most important specific facts, claims, numbers or conclusions
- published_date: the publication date if it appears in the content, else null
- language: ISO 639-1 code of the content language (e.g. "en", "cs")
Write summary and key_points in the same language as the content."""


class Summary(BaseModel):
    title: str
    summary: str
    key_points: list[str] = Field(default_factory=list)
    published_date: date | None = None
    language: str | None = None


async def summarise(llm: LLM, markdown: str) -> Summary:
    return await llm.structured(SYSTEM_PROMPT, markdown[:SUMMARY_INPUT_MAX_CHARS], Summary)
