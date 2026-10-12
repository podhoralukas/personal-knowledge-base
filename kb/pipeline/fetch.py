"""Turn a URL or browser-supplied HTML into markdown."""

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, HTTPCrawlerConfig
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy
from pydantic import BaseModel

from kb.config import FETCH_EXCLUDED_TAGS, FETCH_TIMEOUT_MS, FETCH_USER_AGENT

_RUN_CONFIG = CrawlerRunConfig(excluded_tags=FETCH_EXCLUDED_TAGS, page_timeout=FETCH_TIMEOUT_MS, verbose=False)


class FetchError(Exception):
    @classmethod
    def from_crawl4ai(cls, message: str | None) -> "FetchError":
        """crawl4ai's error_message is a multi-line report with a code excerpt; keep only the cause."""
        for line in (message or "").splitlines():
            if line.startswith("Error: "):
                return cls(line.removeprefix("Error: "))
        return cls((message or "fetch failed").splitlines()[0])


class Fetched(BaseModel):
    url: str
    """Final URL after redirects."""
    markdown: str


def _strategy() -> AsyncHTTPCrawlerStrategy:
    return AsyncHTTPCrawlerStrategy(browser_config=HTTPCrawlerConfig(headers={"User-Agent": FETCH_USER_AGENT}))


async def _run(target: str, config: CrawlerRunConfig) -> Fetched:
    async with AsyncWebCrawler(crawler_strategy=_strategy()) as crawler:
        result = await crawler.arun(target, config=config)
    if not result.success:
        raise FetchError.from_crawl4ai(result.error_message)
    return Fetched(url=result.redirected_url or result.url, markdown=result.markdown.raw_markdown or "")


async def fetch(url: str) -> Fetched:
    return await _run(url, _RUN_CONFIG)


async def html_to_markdown(html: str, base_url: str) -> str:
    fetched = await _run(f"raw:{html}", _RUN_CONFIG.clone(base_url=base_url))
    return fetched.markdown
