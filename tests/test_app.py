import pytest
from fastapi.testclient import TestClient

from kb.app import create_app
from kb.config import Settings
from kb.llm.fake import FakeLLM
from kb.pipeline.run import Pipeline
from kb.pipeline.summarise import Summary
from kb.pipeline.tag import Tagging
from kb.storage.memory import MemoryStorage

HTML = """<html><body><article><h1>Hello</h1>
<p>World. This paragraph is here so the page looks like a real article to the crawler.</p></article></body></html>"""
AUTH = {"Authorization": "Bearer secret"}


@pytest.fixture
def llm():
    return FakeLLM(answers=[Summary(title="Hello", summary="Greets the world.")])


@pytest.fixture
def storage():
    return MemoryStorage()


@pytest.fixture
def client(llm, storage):
    pipeline = Pipeline(storage, llm)
    app = create_app(Settings(api_token="secret", _env_file=None), pipeline=pipeline)
    with TestClient(app) as client:
        yield client


def test_health_needs_no_token(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic secret"}])
def test_capture_rejects_missing_or_wrong_token(client, headers):
    r = client.post("/capture", json={"url": "https://example.com/a", "channel": "manual"}, headers=headers)
    assert r.status_code == 401


def test_no_token_configured_rejects_everything(llm):
    app = create_app(Settings(_env_file=None), pipeline=Pipeline(MemoryStorage(), llm))
    with TestClient(app) as client:
        assert client.get("/items/x", headers=AUTH).status_code == 401


def test_capture_returns_202_and_enriches_in_background(client, llm):
    body = {"url": "https://example.com/a", "content": HTML, "channel": "extension"}
    r = client.post("/capture", json=body, headers=AUTH)
    assert r.status_code == 202
    ids = r.json()
    assert set(ids) == {"item_id", "version_id"}
    assert ids["version_id"].startswith(ids["item_id"] + ":")

    # TestClient runs background tasks before returning, so the result is already there.
    version = client.get(f"/versions/{ids['version_id']}", headers=AUTH).json()
    assert version["status"] == "enriched"
    assert version["enrichment"]["title"] == "Hello"
    assert version["content"] is None

    item = client.get(f"/items/{ids['item_id']}", headers=AUTH).json()
    assert item["current_version_id"] == ids["version_id"]
    assert item["summary"] == "Greets the world."

    versions = client.get(f"/items/{ids['item_id']}/versions", headers=AUTH).json()
    assert [v["id"] for v in versions] == [ids["version_id"]]


@pytest.mark.parametrize("content", [HTML, None])
def test_capture_rejects_invalid_url(client, content):
    r = client.post("/capture", json={"url": "not a url", "content": content, "channel": "manual"}, headers=AUTH)
    assert r.status_code == 422


def test_capture_rejects_unknown_channel(client):
    r = client.post("/capture", json={"url": "https://example.com/a", "channel": "pigeon"}, headers=AUTH)
    assert r.status_code == 422


def test_capture_reports_fetch_failure(client):
    r = client.post("/capture", json={"url": "http://127.0.0.1:1/", "channel": "manual"}, headers=AUTH)
    assert r.status_code == 502


def test_unknown_ids_are_404(client):
    assert client.get("/items/nope", headers=AUTH).status_code == 404
    assert client.get("/versions/nope", headers=AUTH).status_code == 404
    assert client.get("/items/nope/versions", headers=AUTH).json() == []


def test_search_returns_items_and_needs_a_token(client):
    ids = capture(client)
    r = client.get("/search", params={"q": "greets world"}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["semantic"] is True
    assert [i["id"] for i in body["items"]] == [ids["item_id"]]
    assert "embedding" not in body["items"][0]
    assert client.get("/search", params={"q": "x"}).status_code == 401
    assert client.get("/search", params={"q": ""}, headers=AUTH).status_code == 422


def test_search_by_saved_date(client):
    ids = capture(client)  # saved now
    params = {"q": "greets world"}
    today = client.get("/search", params={**params, "from": "2000-01-01"}, headers=AUTH).json()
    assert [i["id"] for i in today["items"]] == [ids["item_id"]]
    assert client.get("/search", params={**params, "to": "2000-01-01"}, headers=AUTH).json()["items"] == []

    r = client.get("/search", params={**params, "from": "2026-10-06", "to": "2026-10-05"}, headers=AUTH)
    assert (r.status_code, r.json()["detail"]) == (422, "the start date is after the end date")
    assert client.get("/search", params={**params, "from": "2026-13-40"}, headers=AUTH).status_code == 422


def capture(client, url="https://example.com/a") -> dict:
    r = client.post("/capture", json={"url": url, "content": HTML, "channel": "extension"}, headers=AUTH)
    assert r.status_code == 202
    return r.json()


def test_delete_item_removes_it_with_its_versions(client):
    ids = capture(client)
    assert client.delete(f"/items/{ids['item_id']}").status_code == 401

    assert client.delete(f"/items/{ids['item_id']}", headers=AUTH).status_code == 204
    assert client.get(f"/items/{ids['item_id']}", headers=AUTH).status_code == 404
    assert client.get(f"/versions/{ids['version_id']}", headers=AUTH).status_code == 404
    assert client.delete(f"/items/{ids['item_id']}", headers=AUTH).status_code == 404


@pytest.mark.parametrize(
    "origin", ["chrome-extension://abcdefghijklmnop", "moz-extension://1b2c3d4e-0000-4f00-9a00-1234567890ab"]
)
def test_extension_origins_may_call_the_api(client, origin):
    preflight = {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    }
    r = client.options("/capture", headers=preflight)
    assert (r.status_code, r.headers["access-control-allow-origin"]) == (200, origin)
    r = client.get("/taxonomy", headers={**AUTH, "Origin": origin})
    assert r.headers["access-control-allow-origin"] == origin


def test_websites_may_not_call_the_api(client):
    preflight = {"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    assert "access-control-allow-origin" not in client.options("/capture", headers=preflight).headers
    assert (
        "access-control-allow-origin"
        not in client.get("/taxonomy", headers={**AUTH, "Origin": "https://evil.example"}).headers
    )


def test_taxonomy_starts_empty(client):
    assert client.get("/taxonomy", headers=AUTH).json() == {"tags": [], "version": 0}


def test_add_tags_and_read_the_taxonomy(client):
    r = client.post("/taxonomy/tags", json={"path": "ai", "description": "AI"}, headers=AUTH)
    assert r.status_code == 201
    assert r.json()["created_in_taxonomy_version"] == 1
    client.post("/taxonomy/tags", json={"path": "ai/rag"}, headers=AUTH)

    taxonomy = client.get("/taxonomy", headers=AUTH).json()
    assert taxonomy["version"] == 2
    assert [(t["path"], t["description"]) for t in taxonomy["tags"]] == [("ai", "AI"), ("ai/rag", "")]


@pytest.mark.parametrize(
    ("body", "code"),
    [({"path": "ai"}, 409), ({"path": "Bad Path"}, 422), ({"path": "nope/child"}, 422), ({}, 422)],
)
def test_add_tag_errors(client, body, code):
    client.post("/taxonomy/tags", json={"path": "ai"}, headers=AUTH)
    assert client.post("/taxonomy/tags", json=body, headers=AUTH).status_code == code


def test_taxonomy_endpoints_need_a_token(client):
    assert client.get("/taxonomy").status_code == 401
    assert client.post("/taxonomy/tags", json={"path": "ai"}).status_code == 401
    assert client.post("/taxonomy/retag").status_code == 401


def test_capture_channel_retag_is_rejected(client):
    r = client.post(
        "/capture", json={"url": "https://example.com/a", "content": HTML, "channel": "retag"}, headers=AUTH
    )
    assert r.status_code == 422


def test_untagged_list_then_retag(client, llm):
    ids = capture(client)
    untagged = client.get("/items/untagged", headers=AUTH).json()
    assert [i["id"] for i in untagged] == [ids["item_id"]]
    assert "embedding" not in untagged[0]

    client.post("/taxonomy/tags", json={"path": "ai"}, headers=AUTH)
    llm.answers = [Tagging(tags=["ai"])]
    r = client.post("/taxonomy/retag", headers=AUTH)
    assert r.status_code == 202
    assert r.json() == {"taxonomy_version": 1, "item_count": 1}

    assert client.get("/items/untagged", headers=AUTH).json() == []
    item = client.get(f"/items/{ids['item_id']}", headers=AUTH).json()
    assert (item["tags"], item["taxonomy_version"]) == (["ai"], 1)
    versions = client.get(f"/items/{ids['item_id']}/versions", headers=AUTH).json()
    assert [v["channel"] for v in versions] == ["retag", "extension"]

    # Already tagged against version 1: nothing to do unless forced.
    assert client.post("/taxonomy/retag", headers=AUTH).json()["item_count"] == 0
    llm.answers = [Tagging(tags=["ai"])]
    assert client.post("/taxonomy/retag?all=true", headers=AUTH).json()["item_count"] == 1


def test_capture_with_picked_tags(client, llm):
    client.post("/taxonomy/tags", json={"path": "ai"}, headers=AUTH)
    body = {"url": "https://example.com/a", "content": HTML, "channel": "extension", "tags": ["ai"]}
    ids = client.post("/capture", json=body, headers=AUTH).json()
    item = client.get(f"/items/{ids['item_id']}", headers=AUTH).json()
    assert (item["tags"], item["annotations"]["owner_tags"]) == (["ai"], ["ai"])

    body["tags"] = ["nope"]
    r = client.post("/capture", json=body, headers=AUTH)
    assert (r.status_code, r.json()["detail"]) == (422, "tags not in the taxonomy: nope")


def test_note_at_capture_and_edit(client, llm):
    body = {"url": "https://example.com/a", "content": HTML, "channel": "extension", "note": "for the talk"}
    iid = client.post("/capture", json=body, headers=AUTH).json()["item_id"]
    assert client.get(f"/items/{iid}", headers=AUTH).json()["annotations"]["notes"] == "for the talk"

    r = client.put(f"/items/{iid}/notes", json={"notes": "rewritten"}, headers=AUTH)
    assert (r.status_code, r.json()["annotations"]["notes"]) == (200, "rewritten")
    assert client.put(f"/items/{iid}/notes", json={"notes": ""}, headers=AUTH).json()["annotations"]["notes"] == ""
    assert client.put("/items/nope/notes", json={"notes": "x"}, headers=AUTH).status_code == 404
    assert client.put(f"/items/{iid}/notes", json={"notes": "x" * 20_001}, headers=AUTH).status_code == 422


def test_owner_tag_endpoints(client, llm):
    client.post("/taxonomy/tags", json={"path": "ai"}, headers=AUTH)
    client.post("/taxonomy/tags", json={"path": "ai/rag"}, headers=AUTH)
    llm.answers.append(Tagging(tags=[]))
    iid = capture(client)["item_id"]

    r = client.post(f"/items/{iid}/tags", json={"path": "ai/rag"}, headers=AUTH)
    assert (r.status_code, r.json()["tags"]) == (200, ["ai/rag"])

    r = client.delete(f"/items/{iid}/tags/ai/rag", headers=AUTH)
    assert (r.status_code, r.json()["tags"], r.json()["annotations"]["rejected_tags"]) == (200, [], ["ai/rag"])

    r = client.delete(f"/items/{iid}/rejected-tags/ai/rag", headers=AUTH)
    assert (r.status_code, r.json()["annotations"]["rejected_tags"]) == (200, [])

    assert client.post(f"/items/{iid}/tags", json={"path": "nope"}, headers=AUTH).status_code == 422
    assert client.delete(f"/items/{iid}/tags/ai", headers=AUTH).status_code == 422
    assert client.post("/items/nope/tags", json={"path": "ai"}, headers=AUTH).status_code == 404
    assert client.post(f"/items/{iid}/tags", json={"path": "ai"}).status_code == 401


def test_change_and_delete_tags(client):
    for path in ("ai", "ai/reserach", "news"):
        client.post("/taxonomy/tags", json={"path": path}, headers=AUTH)

    r = client.patch("/taxonomy/tags/ai/reserach", json={"path": "ai/research", "description": "Papers"}, headers=AUTH)
    assert (r.status_code, r.json()["path"], r.json()["description"]) == (200, "ai/research", "Papers")
    r = client.patch("/taxonomy/tags/news", json={"description": "Media"}, headers=AUTH)
    assert (r.status_code, r.json()["description"]) == (200, "Media")

    assert client.patch("/taxonomy/tags/nope", json={"description": "x"}, headers=AUTH).status_code == 404
    assert client.patch("/taxonomy/tags/news", json={"path": "ai"}, headers=AUTH).status_code == 409
    r = client.patch("/taxonomy/tags/news", json={"path": "x/news", "description": "lost"}, headers=AUTH)
    assert r.status_code == 422
    assert client.get("/taxonomy", headers=AUTH).json()["tags"][-1]["description"] == "Media"  # nothing half-applied

    assert client.delete("/taxonomy/tags/ai", headers=AUTH).status_code == 409  # has a sub-tag
    assert client.delete("/taxonomy/tags/news", headers=AUTH).status_code == 204
    assert client.delete("/taxonomy/tags/news", headers=AUTH).status_code == 404
    assert [t["path"] for t in client.get("/taxonomy", headers=AUTH).json()["tags"]] == ["ai", "ai/research"]
    assert client.delete("/taxonomy/tags/ai/research").status_code == 401


class TestThoughts:
    def test_write_returns_202_and_enriches_in_background(self, client, llm):
        llm.answers = []  # empty Taxonomy: no tag call
        body = {"title": "Salt", "text": "Soup needs salt.", "written_at": "2026-09-01T09:00:00Z"}
        r = client.post("/thoughts", json=body, headers=AUTH)
        assert r.status_code == 202
        ids = r.json()
        item = client.get(f"/items/{ids['item_id']}", headers=AUTH).json()
        assert (item["media_type"], item["title"], item["text"], item["original_url"]) == (
            "thought",
            "Salt",
            "Soup needs salt.",
            None,
        )
        version = client.get(f"/versions/{ids['version_id']}", headers=AUTH).json()
        assert version["status"] == "enriched"
        assert client.post("/thoughts", json=body, headers=AUTH).json() == ids  # same written_at: same Thought

    @pytest.mark.parametrize("body", [{"text": " "}, {"text": "x", "tags": ["nope"]}, {"title": "no text"}])
    def test_invalid_thoughts_are_422(self, client, body):
        assert client.post("/thoughts", json=body, headers=AUTH).status_code == 422

    def test_edit_adds_a_version(self, client, llm):
        llm.answers = []
        ids = client.post("/thoughts", json={"text": "One"}, headers=AUTH).json()
        r = client.put(f"/thoughts/{ids['item_id']}", json={"text": "Two"}, headers=AUTH)
        assert r.status_code == 202 and r.json()["version_id"] != ids["version_id"]
        assert client.get(f"/items/{ids['item_id']}", headers=AUTH).json()["text"] == "Two"
        assert len(client.get(f"/items/{ids['item_id']}/versions", headers=AUTH).json()) == 2

    def test_edit_unknown_is_404_and_article_is_422(self, client):
        assert client.put("/thoughts/nope", json={"text": "x"}, headers=AUTH).status_code == 404
        body = {"url": "https://example.com/a", "content": HTML, "channel": "extension"}
        article = client.post("/capture", json=body, headers=AUTH).json()["item_id"]
        assert client.put(f"/thoughts/{article}", json={"text": "x"}, headers=AUTH).status_code == 422

    def test_retry_needs_a_failed_version(self, client, llm):
        llm.answers = []
        ids = client.post("/thoughts", json={"text": "One"}, headers=AUTH).json()
        assert client.post(f"/thoughts/{ids['item_id']}/retry", headers=AUTH).status_code == 409
        assert client.post("/thoughts/nope/retry", headers=AUTH).status_code == 404

    def test_a_thought_has_no_note(self, client, llm):
        llm.answers = []
        ids = client.post("/thoughts", json={"text": "One"}, headers=AUTH).json()
        assert client.put(f"/items/{ids['item_id']}/notes", json={"notes": "x"}, headers=AUTH).status_code == 422

    def test_kind_filters_search_and_untagged(self, client, llm):
        llm.answers = [Summary(title="Soup article", summary="About soup.")]
        body = {"url": "https://example.com/a", "content": HTML, "channel": "extension"}
        client.post("/capture", json=body, headers=AUTH)
        client.post("/thoughts", json={"text": "Soup thought"}, headers=AUTH)

        def kinds(path: str) -> list[str]:
            r = client.get(path, headers=AUTH).json()
            return sorted(i["media_type"] for i in (r["items"] if "items" in r else r))

        assert kinds("/search?q=soup") == ["article", "thought"]
        assert kinds("/search?q=soup&kind=thought") == ["thought"]
        assert kinds("/items/untagged?kind=article") == ["article"]
        assert client.get("/search?q=soup&kind=video", headers=AUTH).status_code == 422


class TestDeleteVersion:
    def test_delete_falls_back_and_refuses_the_last(self, client, llm):
        llm.answers = []
        ids = client.post("/thoughts", json={"text": "One"}, headers=AUTH).json()
        second = client.put(f"/thoughts/{ids['item_id']}", json={"text": "Two"}, headers=AUTH).json()

        assert client.delete(f"/versions/{second['version_id']}", headers=AUTH).status_code == 204
        assert client.get(f"/items/{ids['item_id']}", headers=AUTH).json()["text"] == "One"
        r = client.delete(f"/versions/{ids['version_id']}", headers=AUTH)
        assert r.status_code == 409 and "delete the item instead" in r.json()["detail"]
        assert client.delete("/versions/nope", headers=AUTH).status_code == 404


class TestItemList:
    def test_newest_first_filtered_by_tag_kind_and_date(self, client, llm):
        client.post("/taxonomy/tags", json={"path": "ai"}, headers=AUTH)
        client.post("/taxonomy/tags", json={"path": "ai/rag"}, headers=AUTH)
        llm.answers.append(Tagging(tags=["ai/rag"]))
        article = capture(client)["item_id"]
        llm.answers = [Tagging(tags=[])]
        thought = client.post("/thoughts", json={"text": "Soup"}, headers=AUTH).json()["item_id"]

        def listed(**params) -> list[str]:
            r = client.get("/items", params=params, headers=AUTH)
            assert r.status_code == 200
            return [i["id"] for i in r.json()]

        assert listed() == [thought, article]
        assert listed(tag="ai") == [article]  # sub-tags included
        assert listed(kind="thought") == [thought]
        assert listed(**{"from": "2000-01-01"}) == [thought, article]
        assert listed(to="2000-01-01") == []
        assert "embedding" not in client.get("/items", headers=AUTH).json()[0]

        r = client.get("/items", params={"from": "2026-10-06", "to": "2026-10-05"}, headers=AUTH)
        assert (r.status_code, r.json()["detail"]) == (422, "the start date is after the end date")
        assert client.get("/items").status_code == 401

    def test_untagged_by_date(self, client):
        ids = capture(client)
        assert [i["id"] for i in client.get("/items/untagged?from=2000-01-01", headers=AUTH).json()] == [ids["item_id"]]
        assert client.get("/items/untagged?to=2000-01-01", headers=AUTH).json() == []


def test_no_embeddings_in_item_and_version_responses(client):
    ids = capture(client)
    assert "embedding" not in client.get(f"/items/{ids['item_id']}", headers=AUTH).json()
    assert "embedding" not in client.put(f"/items/{ids['item_id']}/notes", json={"notes": "x"}, headers=AUTH).json()
    version = client.get(f"/versions/{ids['version_id']}", headers=AUTH).json()
    assert version["enrichment"]["title"] == "Hello" and "embedding" not in version["enrichment"]
    versions = client.get(f"/items/{ids['item_id']}/versions", headers=AUTH).json()
    assert "embedding" not in versions[0]["enrichment"]


def test_taxonomy_stats(client, llm):
    for path in ("ai", "ai/rag", "cooking"):
        client.post("/taxonomy/tags", json={"path": path}, headers=AUTH)
    llm.answers.append(Tagging(tags=["ai/rag"]))
    capture(client)
    llm.answers += [Summary(title="Other", summary="Other."), Tagging(tags=[])]
    capture(client, "https://example.com/b")

    r = client.get("/taxonomy/stats", headers=AUTH)
    assert r.json() == {
        "items": 2,
        "untagged": 1,
        "counts": {"ai": 1, "ai/rag": 1, "cooking": 0},
        "deletable": ["cooking"],
    }
    assert client.get("/taxonomy/stats").status_code == 401


class TestCookieLogin:
    CSRF = {"X-KB-CSRF": "1"}

    def test_login_sets_a_strict_http_only_cookie(self, client):
        r = client.post("/auth/login", json={"token": "secret"})
        assert r.status_code == 204
        cookie = r.headers["set-cookie"]
        assert cookie.startswith("kb_token=secret;")
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie

    def test_wrong_token_sets_no_cookie(self, client):
        r = client.post("/auth/login", json={"token": "wrong"})
        assert r.status_code == 401 and "set-cookie" not in r.headers

    def test_the_cookie_needs_the_csrf_header(self, client):
        client.post("/auth/login", json={"token": "secret"})
        assert client.get("/taxonomy").status_code == 401
        assert client.get("/taxonomy", headers=self.CSRF).status_code == 200

    def test_a_wrong_cookie_is_rejected(self, client):
        client.cookies.set("kb_token", "wrong")
        assert client.get("/taxonomy", headers=self.CSRF).status_code == 401

    def test_logout_clears_the_cookie(self, client):
        client.post("/auth/login", json={"token": "secret"})
        assert client.post("/auth/logout").status_code == 204
        assert client.get("/taxonomy", headers=self.CSRF).status_code == 401

    def test_websites_may_not_send_the_csrf_header(self, client):
        preflight = {
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-kb-csrf",
        }
        assert "access-control-allow-origin" not in client.options("/taxonomy", headers=preflight).headers


class TestWebApp:
    @pytest.fixture
    def serving(self, monkeypatch, llm):
        """A client of the app serving the React build from `dist`."""

        def client(dist):
            monkeypatch.setattr("kb.app.WEB_DIST_DIR", dist)
            app = create_app(Settings(api_token="secret", _env_file=None), pipeline=Pipeline(MemoryStorage(), llm))
            return TestClient(app)

        return client

    @pytest.fixture
    def web(self, tmp_path, serving):
        (tmp_path / "assets").mkdir()
        (tmp_path / "index.html").write_text("<div id=root></div>")
        (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)")
        with serving(tmp_path) as client:
            yield client

    def test_serves_the_built_app_without_a_login(self, web):
        r = web.get("/app/")
        assert (r.status_code, r.text, r.headers["cache-control"]) == (200, "<div id=root></div>", "no-cache")
        r = web.get("/app/assets/index-abc123.js")
        assert r.status_code == 200 and "cache-control" not in r.headers

    def test_app_routes_get_index_html_but_missing_files_are_404(self, web):
        assert web.get("/app/taxonomy").text == "<div id=root></div>"
        assert web.get("/app/assets/gone.js").status_code == 404

    def test_a_missing_build_says_so(self, tmp_path, serving):
        with serving(tmp_path / "missing") as client:
            for path in ("/app/", "/app/taxonomy"):
                r = client.get(path)
                assert r.status_code == 404 and "npm run build" in r.json()["detail"]
