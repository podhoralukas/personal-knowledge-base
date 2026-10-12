import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from kb.pipeline.fetch import FetchError, fetch, html_to_markdown

# Realistic size on purpose: crawl4ai treats pages with < 50 visible characters as bot-blocked.
PAGE = b"""<html><body>
<nav>menu</nav>
<article><h1>Hello</h1>
<p>World <a href='/x'>link</a>. This paragraph is here so the page looks like a real article to the crawler.</p>
</article>
<footer>f</footer>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/old":
            self.send_response(301)
            self.send_header("Location", "/new")
            self.end_headers()
        elif self.path == "/new":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(PAGE)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def base_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


async def test_fetch_returns_markdown_without_excluded_tags(base_url):
    fetched = await fetch(f"{base_url}/new")
    assert fetched.url == f"{base_url}/new"
    assert "Hello" in fetched.markdown and "World" in fetched.markdown
    assert "menu" not in fetched.markdown


async def test_fetch_follows_redirects_and_reports_final_url(base_url):
    fetched = await fetch(f"{base_url}/old")
    assert fetched.url == f"{base_url}/new"
    assert "Hello" in fetched.markdown


async def test_fetch_raises_on_http_error(base_url):
    with pytest.raises(FetchError):
        await fetch(f"{base_url}/missing")


async def test_fetch_raises_on_unreachable_host():
    with pytest.raises(FetchError):
        await fetch("http://127.0.0.1:1/")


async def test_html_to_markdown_resolves_links_against_base_url():
    markdown = await html_to_markdown(PAGE.decode(), base_url="https://example.com/a")
    assert markdown.startswith("# Hello\nWorld [link](https://example.com/x). This paragraph")


def test_fetch_error_keeps_only_the_cause():
    raw = "Unexpected error in _crawl_web at line 2796\nError: HTTP request failed: HTTP 403\n\nCode context:\n2791 x"
    assert str(FetchError.from_crawl4ai(raw)) == "HTTP request failed: HTTP 403"
    assert str(FetchError.from_crawl4ai(None)) == "fetch failed"
