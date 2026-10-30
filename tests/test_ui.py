from datetime import UTC, datetime
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from kb.app import create_app
from kb.config import UI_TOKEN_COOKIE, Settings
from kb.llm.fake import FakeLLM
from kb.models import CaptureRequest, Channel, Enrichment, Item, Version
from kb.pipeline.run import Pipeline
from kb.pipeline.summarise import Summary
from kb.storage.memory import MemoryStorage

T1 = datetime(2026, 9, 21, 14, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 9, 22, 9, 0, 0, tzinfo=UTC)
HTML = """<html><body><article><h1>Hello</h1>
<p>World. This paragraph is here so the page looks like a real article to the crawler.</p></article></body></html>"""


def enriched(url: str, at: datetime, title: str, tags: list[str]) -> Version:
    enrichment = Enrichment(
        title=title,
        summary=f"Summary of {title}.",
        key_points=[f"Point about {title}"],
        tags=tags,
        model="m",
        prompt_version="1",
        taxonomy_version=1,
        embedding_model="e",
        tag_model="m",
        tag_prompt_version="1",
    )
    return Version.create(CaptureRequest(url=url, channel=Channel.MANUAL), at, "text").enriched(enrichment)


@pytest.fixture
def storage():
    s = MemoryStorage()
    for v in (
        enriched("https://example.com/rag", T1, "RAG explained", ["ai/rag"]),
        enriched("https://example.com/soup", T2, "Tomato soup", ["cooking"]),
    ):
        s.put_version(v)
        s.put_item(Item.from_version(v))
    return s


@pytest.fixture
def llm():
    return FakeLLM(answers=[Summary(title="Hello", summary="Greets the world.")])


@pytest.fixture
def anonymous(storage, llm):
    app = create_app(Settings(api_token="secret", _env_file=None), pipeline=Pipeline(storage, llm))
    with TestClient(app, follow_redirects=False) as client:
        yield client


@pytest.fixture
def client(anonymous):
    assert anonymous.post("/ui/login", data={"token": "secret"}).status_code == 303
    return anonymous


def item_id(storage, title: str) -> str:
    return next(i.id for i in storage.items.values() if i.title == title)


class TestLogin:
    def test_pages_redirect_to_login(self, anonymous):
        r = anonymous.get("/ui")
        assert (r.status_code, r.headers["location"]) == (303, "/ui/login?next=/ui")

    def test_htmx_requests_get_hx_redirect(self, anonymous):
        r = anonymous.get("/ui/versions/x", headers={"HX-Request": "true"})
        assert (r.status_code, r.headers["hx-redirect"]) == (401, "/ui/login?next=/ui/versions/x")

    def test_wrong_token_is_rejected(self, anonymous):
        r = anonymous.post("/ui/login", data={"token": "nope", "next": "/ui"})
        assert r.status_code == 401
        assert "Wrong token." in r.text
        assert UI_TOKEN_COOKIE not in anonymous.cookies

    def test_login_sets_cookie_and_returns_to_next(self, anonymous):
        r = anonymous.post("/ui/login", data={"token": "secret", "next": "/ui?tag=ai"})
        assert (r.status_code, r.headers["location"]) == (303, "/ui?tag=ai")
        assert "httponly" in r.headers["set-cookie"].lower()
        assert anonymous.get("/ui").status_code == 200

    @pytest.mark.parametrize("next_url", ["https://evil.example", "//evil.example", "/docs"])
    def test_login_never_redirects_outside_the_ui(self, anonymous, next_url):
        r = anonymous.post("/ui/login", data={"token": "secret", "next": next_url})
        assert r.headers["location"] == "/ui"

    def test_logout_clears_cookie(self, client):
        r = client.post("/ui/logout")
        assert (r.status_code, r.headers["location"]) == (303, "/ui/login")
        assert client.get("/ui").status_code == 303

    def test_no_configured_token_never_logs_in(self, storage, llm):
        app = create_app(Settings(_env_file=None), pipeline=Pipeline(storage, llm))
        with TestClient(app, follow_redirects=False) as c:
            assert c.post("/ui/login", data={"token": "anything"}).status_code == 401

    def test_cookie_does_not_authorise_the_json_api(self, client, storage):
        assert client.get(f"/items/{item_id(storage, 'RAG explained')}").status_code == 401


class TestItems:
    def test_lists_items_newest_first(self, client):
        html = client.get("/ui").text
        assert html.index("Tomato soup") < html.index("RAG explained")
        assert "2 items" in html

    def test_tag_filter_includes_sub_tags(self, client):
        html = client.get("/ui", params={"tag": "ai"}).text
        assert "RAG explained" in html
        assert "Tomato soup" not in html
        assert "1 item<" in html

    def test_empty_tag(self, client):
        assert "No items under this tag." in client.get("/ui", params={"tag": "nope"}).text

    def test_item_page_shows_summary_and_versions(self, client, storage):
        iid = item_id(storage, "RAG explained")
        html = client.get(f"/ui/items/{iid}").text
        assert "Summary of RAG explained." in html
        assert "Point about RAG explained" in html
        assert 'href="/ui?tag=ai/rag"' in html
        assert "2026-09-21 14:00 UTC" in html
        assert "hx-trigger" not in html

    def test_version_details_partial(self, client, storage):
        version = next(v for v in storage.versions.values() if v.enrichment.title == "Tomato soup")
        html = client.get(f"/ui/versions/{version.id}").text
        assert version.id in html
        assert "taxonomy v1" in html
        assert "<html" not in html

    def test_unknown_ids_are_404_pages(self, client):
        assert client.get("/ui/items/nope").status_code == 404
        assert client.get("/ui/versions/nope").status_code == 404
        assert client.post("/ui/items/nope/delete").status_code == 404

    def test_delete_returns_to_the_list_without_the_item(self, client, storage):
        iid = item_id(storage, "RAG explained")
        assert f'action="/ui/items/{iid}/delete"' in client.get(f"/ui/items/{iid}").text

        r = client.post(f"/ui/items/{iid}/delete")
        assert (r.status_code, r.headers["location"]) == (303, "/ui")
        assert "RAG explained" not in client.get("/ui").text
        assert storage.list_versions(iid) == []

    def test_delete_needs_login(self, anonymous, storage):
        iid = item_id(storage, "RAG explained")
        assert anonymous.post(f"/ui/items/{iid}/delete").status_code == 303
        assert storage.get_item(iid) is not None


class TestItemTags:
    @pytest.fixture
    def iid(self, storage):
        from kb.taxonomy import add_tag

        for path in ("ai", "ai/rag", "cooking"):
            add_tag(storage, path)
        return item_id(storage, "RAG explained")

    def test_item_page_offers_untag_and_add(self, client, iid):
        html = client.get(f"/ui/items/{iid}").text
        assert 'action="/ui/items/' + iid + '/untag"' in html
        assert 'aria-label="Remove ai/rag"' in html
        assert '<option value="cooking">' in html
        assert '<option value="ai/rag">' not in html  # already on the item

    def test_untag_then_allow_again(self, client, storage, iid):
        r = client.post(f"/ui/items/{iid}/untag", data={"path": "ai/rag"})
        assert (r.status_code, r.headers["location"]) == (303, f"/ui/items/{iid}")
        html = client.get(f"/ui/items/{iid}").text
        assert "never suggested again" in html
        assert '<span class="tag rejected">ai/rag</span>' in html

        client.post(f"/ui/items/{iid}/allow", data={"path": "ai/rag"})
        assert storage.get_item(iid).tags == ["ai/rag"]
        assert "never suggested again" not in client.get(f"/ui/items/{iid}").text

    def test_add_by_hand_is_marked_as_the_owners(self, client, storage, iid):
        client.post(f"/ui/items/{iid}/tags", data={"path": "cooking"})
        assert storage.get_item(iid).tags == ["ai/rag", "cooking"]
        assert 'class="tag owner" href="/ui?tag=cooking"' in client.get(f"/ui/items/{iid}").text

    def test_invalid_edit_shows_the_error_on_the_item_page(self, client, iid):
        r = client.post(f"/ui/items/{iid}/untag", data={"path": "cooking"})
        assert r.status_code == 422
        assert "the item is not tagged" in r.text
        assert "RAG explained" in r.text

    def test_versions_show_picked_tags(self, client, storage, iid):
        from kb.models import Enrichment

        request = CaptureRequest(url="https://example.com/p", channel=Channel.EXTENSION, tags=["cooking"])
        e = Enrichment(
            title="Picked", summary="S", model="m", prompt_version="1", taxonomy_version=3, embedding_model="e"
        )
        v = Version.create(request, T2, "text").enriched(e)
        storage.put_version(v)
        storage.put_item(Item.from_version(v))
        assert 'cooking <span class="muted">(picked)</span>' in client.get(f"/ui/items/{v.item_id}").text
        assert "picked by you: cooking" in client.get(f"/ui/versions/{v.id}").text

    def test_unknown_item_is_404(self, client, iid):
        assert client.post("/ui/items/nope/tags", data={"path": "ai"}).status_code == 404


class TestItemNote:
    @pytest.fixture
    def iid(self, storage):
        return item_id(storage, "RAG explained")

    def test_add_edit_and_clear(self, client, storage, iid):
        assert "+ add a note" in client.get(f"/ui/items/{iid}").text

        r = client.post(f"/ui/items/{iid}/notes", data={"notes": "line one\r\nline two"})
        assert (r.status_code, r.headers["location"]) == (303, f"/ui/items/{iid}")
        assert storage.get_item(iid).annotations.notes == "line one\nline two"
        html = client.get(f"/ui/items/{iid}").text
        assert '<p class="note">line one\nline two</p>' in html
        assert "<summary>edit</summary>" in html

        client.post(f"/ui/items/{iid}/notes", data={"notes": "  "})
        assert storage.get_item(iid).annotations.notes == ""
        assert '<p class="note">' not in client.get(f"/ui/items/{iid}").text

    def test_too_long_keeps_the_draft_open(self, client, storage, iid):
        r = client.post(f"/ui/items/{iid}/notes", data={"notes": "y" * 20_001})
        assert r.status_code == 422
        assert "The note is too long" in r.text
        assert '<details class="note-edit" open>' in r.text
        assert storage.get_item(iid).annotations.notes == ""

    def test_version_shows_the_note_it_brought(self, client, storage):
        request = CaptureRequest(url="https://example.com/n", channel=Channel.EXTENSION, note="why I saved it")
        v = Version.create(request, T2, "text")
        storage.put_version(v)
        assert '<dd class="note">why I saved it</dd>' in client.get(f"/ui/versions/{v.id}").text

    def test_unknown_item_is_404(self, client):
        assert client.post("/ui/items/nope/notes", data={"notes": "x"}).status_code == 404


class TestSearch:
    def test_empty_query_shows_the_form_without_searching(self, client, llm):
        html = client.get("/ui/search").text
        assert 'name="q"' in html
        assert "result" not in html
        assert llm.embedded == []

    def test_results_and_tag_options(self, client, storage, llm):
        from kb.taxonomy import add_tag

        add_tag(storage, "ai")
        add_tag(storage, "ai/rag")
        html = client.get("/ui/search", params={"q": "soup"}).text
        assert llm.embedded == ["soup"]
        assert "Tomato soup" in html
        assert "RAG explained" not in html  # no embeddings stored, so only the keyword match is found
        assert '<option value="ai/rag">' in html

    def test_tag_limits_results(self, client):
        html = client.get("/ui/search", params={"q": "summary", "tag": "ai"}).text
        assert "RAG explained" in html
        assert "Tomato soup" not in html


class TestDates:
    """RAG explained was saved 2026-09-21, Tomato soup 2026-09-22."""

    def test_items_saved_in_a_range(self, client):
        html = client.get("/ui", params={"from": "2026-09-22"}).text
        assert "Tomato soup" in html and "RAG explained" not in html
        assert "1 item saved from 2026-09-22 to today" in html
        html = client.get("/ui", params={"to": "2026-09-21"}).text
        assert "RAG explained" in html and "Tomato soup" not in html
        assert "No items" not in client.get("/ui", params={"from": "2026-09-21", "to": "2026-09-22"}).text

    def test_dates_combine_with_the_tag(self, client):
        html = client.get("/ui", params={"tag": "ai", "from": "2026-09-22"}).text
        assert "No items under this tag." in html
        assert '<input type="hidden" name="tag" value="ai">' in html

    def test_cards_show_the_saved_date(self, client):
        assert "saved 2026-09-21 14:00 UTC" in client.get("/ui").text

    def test_presets_fill_both_fields_in_the_form_that_keeps_the_tag(self, client):
        from datetime import UTC, datetime, timedelta

        today = datetime.now(UTC).date()
        html = client.get("/ui", params={"tag": "ai"}).text
        form = html[html.index('<form class="filters"') :]
        form = form[: form.index("</form>")]
        assert '<input type="hidden" name="tag" value="ai">' in form
        assert f'data-from="{today - timedelta(days=7)}" data-to="{today}"' in form
        assert 'data-from="" data-to=""' in form  # All dates clears both
        assert "this.form.elements.from.value = this.dataset.from" in form

    def test_the_range_carries_over_between_views(self, client):
        html = client.get("/ui", params={"from": "2026-09-22"}).text
        assert 'href="/ui/search?from=2026-09-22">Search<' in html
        assert 'href="/ui?tag=cooking&amp;from=2026-09-22"' in html  # tag links on the cards

    def test_search_within_a_range(self, client):
        html = client.get("/ui/search", params={"q": "summary", "from": "2026-09-22"}).text
        assert "Tomato soup" in html and "RAG explained" not in html
        form = html[html.index('<form class="search"') :]
        form = form[: form.index("</form>")]
        assert 'name="q"' in form and 'name="from" value="2026-09-22"' in form  # one form: query, tag and dates

    def test_untagged_within_a_range(self, client, storage):
        v = Version.create(CaptureRequest(url="https://example.com/u", channel=Channel.MANUAL), T1, "text")
        e = Enrichment(
            title="Lonely", summary="S", model="m", prompt_version="1", taxonomy_version=1, embedding_model="e"
        )
        v = v.enriched(e)
        storage.put_version(v)
        storage.put_item(Item.from_version(v))
        assert "Lonely" in client.get("/ui/untagged", params={"to": "2026-09-21"}).text
        assert "Lonely" not in client.get("/ui/untagged", params={"from": "2026-09-22"}).text

    def test_an_invalid_range_filters_nothing_and_says_why(self, client):
        html = client.get("/ui", params={"from": "2026-09-23", "to": "2026-09-21"}).text
        assert "Dates ignored: the start date is after the end date." in html
        assert "Tomato soup" in html and "RAG explained" in html


class TestCapture:
    def test_capture_redirects_to_the_item_which_is_then_enriched(self, client, monkeypatch):
        from kb.pipeline import run
        from kb.pipeline.fetch import Fetched

        async def fake_fetch(url):
            return Fetched(url=url, markdown="# Hello\n\nWorld.")

        monkeypatch.setattr(run, "fetch", fake_fetch)
        r = client.post("/ui/capture", data={"url": " https://example.com/new "})
        assert r.status_code == 303
        location = r.headers["location"]
        assert location.startswith("/ui/items/")

        html = client.get(location).text  # TestClient ran the background enrichment already
        assert "Greets the world." in html
        assert "manual" in html

    def test_pending_capture_page_polls(self, client, storage):
        pending = Version.create(CaptureRequest(url="https://example.com/p", channel=Channel.MANUAL), T1, "text")
        storage.put_version(pending)
        html = client.get(f"/ui/items/{pending.item_id}").text
        assert "Processing…" in html
        assert 'hx-trigger="every 2s"' in html

    def test_failed_capture_page(self, client, storage):
        failed = Version.create(CaptureRequest(url="https://example.com/f", channel=Channel.MANUAL), T1, "text")
        storage.put_version(failed.failed("RuntimeError('boom')"))
        html = client.get(f"/ui/items/{failed.item_id}").text
        assert "Capture failed" in html
        assert "hx-trigger" not in html

    def test_invalid_url_shows_error_on_the_items_page(self, client):
        r = client.post("/ui/capture", data={"url": "not a url"})
        assert r.status_code == 422
        assert "Could not capture" in r.text
        assert "RAG explained" in r.text


class TestTaxonomy:
    @pytest.fixture
    def tags(self, storage):
        from kb.taxonomy import add_tag

        for path in ("cooking", "ai", "ai/rag", "ai-safety"):  # versions 1-4
            add_tag(storage, path, "Retrieval-augmented generation" if path == "ai/rag" else "")

    def test_tree_nests_children_in_path_order_with_counts(self, client, tags):
        html = client.get("/ui/taxonomy").text
        assert "v4" in html
        assert html.index(">ai<") < html.index(">rag<") < html.index(">ai-safety<") < html.index(">cooking<")
        ai = html[html.index('<li id="tag-ai">') : html.index('<li id="tag-ai-safety">')]
        assert '<ul><li id="tag-ai/rag">' in ai.replace("\n", "").replace("  ", "")  # nested under its parent
        assert 'class="toggle" aria-expanded="true"' in ai  # only parents can be collapsed
        assert 'href="/ui?tag=ai/rag"' in html
        assert "Retrieval-augmented generation" in html
        assert 'title="Items under this tag, sub-tags included">1<' in html
        assert "0 untagged items" in html

    def test_empty_taxonomy(self, client):
        html = client.get("/ui/taxonomy").text
        assert "No tags yet." in html
        assert "v0" in html

    def test_each_tag_offers_sub_tag_edit_and_rename(self, client, tags):
        html = client.get("/ui/taxonomy").text
        assert 'name="path" value="ai/rag/"' in html  # + sub-tag is pre-filled with the parent
        assert 'name="description" value="Retrieval-augmented generation"' in html
        assert 'name="new_path" value="ai/rag"' in html

    def test_only_unused_leaf_tags_can_be_deleted(self, client, tags):
        html = client.get("/ui/taxonomy").text  # ai/rag and cooking carry items, ai has a sub-tag
        assert "Delete the tag ai-safety?" in html
        for path in ("ai", "ai/rag", "cooking"):
            assert f"Delete the tag {path}?" not in html

    def test_describe_rename_and_delete(self, client, storage, tags):
        r = client.post("/ui/taxonomy/describe", data={"path": "cooking", "description": "Recipes"})
        assert r.headers["location"] == "/ui/taxonomy?described=cooking"
        assert "Saved the description of" in client.get(r.headers["location"]).text

        r = client.post("/ui/taxonomy/rename", data={"path": "ai/rag", "new_path": " ai/retrieval "})
        assert r.headers["location"] == "/ui/taxonomy?renamed=ai/retrieval"
        assert storage.get_item(item_id(storage, "RAG explained")).tags == ["ai/retrieval"]

        r = client.post("/ui/taxonomy/delete", data={"path": "ai-safety"})
        assert r.headers["location"] == "/ui/taxonomy?deleted=ai-safety"
        assert [t.path for t in storage.get_taxonomy().tags] == ["ai", "ai/retrieval", "cooking"]

    @pytest.mark.parametrize(
        ("url", "data", "code", "message"),
        [
            ("/ui/taxonomy/rename", {"path": "cooking", "new_path": "ai"}, 409, "Tag ai already exists."),
            ("/ui/taxonomy/rename", {"path": "nope", "new_path": "x"}, 404, "Tag nope does not exist."),
            ("/ui/taxonomy/delete", {"path": "cooking"}, 422, "used by items"),
        ],
    )
    def test_change_errors_show_on_the_tree(self, client, tags, url, data, code, message):
        r = client.post(url, data=data)
        assert r.status_code == code
        assert message in r.text
        assert 'class="tree"' in r.text

    def test_add_tag(self, client, storage, tags):
        r = client.post("/ui/taxonomy/tags", data={"path": " ai/agents ", "description": "Agents"})
        assert (r.status_code, r.headers["location"]) == (303, "/ui/taxonomy?added=ai/agents")
        assert storage.get_taxonomy().get("ai/agents").description == "Agents"
        assert "Added <span" in client.get(r.headers["location"]).text

    @pytest.mark.parametrize(
        ("path", "code", "message"),
        [
            ("ai", 409, "Tag ai already exists."),
            ("Bad Path", 422, "invalid tag path"),
            ("nope/x", 422, "does not exist"),
        ],
    )
    def test_add_tag_errors_keep_the_input(self, client, tags, path, code, message):
        r = client.post("/ui/taxonomy/tags", data={"path": path, "description": "kept"})
        assert r.status_code == code
        assert message in r.text
        assert f'value="{path}"' in r.text
        assert 'value="kept"' in r.text

    @pytest.fixture
    def waiting(self, storage, tags):
        """Two Items a new Tag could change: one tagged with the parent of ai/rag, one untagged."""
        for v in (
            enriched("https://example.com/ai", T1, "AI overview", ["ai"]),
            enriched("https://example.com/u", T1, "Unsorted", []),
        ):
            storage.put_version(v)
            storage.put_item(Item.from_version(v))

    def test_retag_panel_counts_items_a_new_tag_could_change(self, client, waiting):
        html = client.get("/ui/taxonomy").text
        assert "2 items could get one of the newest tags" in html
        assert "Re-tag 2<" in html
        assert "Re-tag all 4" in html

    def test_retag_adds_tags_in_the_background(self, client, storage, llm, waiting):
        from kb.pipeline.tag import Tagging

        llm.answers = [Tagging(tags=["ai/rag"]), Tagging(tags=["ai-safety"])]
        r = client.post("/ui/taxonomy/retag")
        assert (r.status_code, r.headers["location"]) == (303, "/ui/taxonomy?retagging=2")
        assert storage.get_item(item_id(storage, "AI overview")).tags == ["ai/rag"]  # the child replaced its parent
        assert storage.get_item(item_id(storage, "Unsorted")).tags == ["ai-safety"]
        assert storage.get_item(item_id(storage, "Tomato soup")).taxonomy_version == 1  # not a candidate

        html = client.get(r.headers["location"]).text
        assert "Re-tagging 2 items in the background." in html
        assert "No item is waiting for the newest tags." in html

    def test_retag_all_never_removes_a_tag(self, client, storage, llm, waiting):
        from kb.pipeline.tag import Tagging

        llm.answers = [Tagging(tags=[]) for _ in range(4)]
        r = client.post("/ui/taxonomy/retag", data={"all": "true"})
        assert r.headers["location"] == "/ui/taxonomy?retagging=4"
        assert llm.answers == []
        assert storage.get_item(item_id(storage, "Tomato soup")).tags == ["cooking"]
        assert storage.get_item(item_id(storage, "RAG explained")).tags == ["ai/rag"]
        assert all(len(storage.list_versions(iid)) == 2 for iid in storage.items)

    def test_untagged_list(self, client, storage):
        v = Version.create(CaptureRequest(url="https://example.com/u", channel=Channel.MANUAL), T2, "text").enriched(
            Enrichment(
                title="Lonely", summary="S", model="m", prompt_version="1", taxonomy_version=1, embedding_model="e"
            )
        )
        storage.put_version(v)
        storage.put_item(Item.from_version(v))
        html = client.get("/ui/untagged").text
        assert "Untagged items" in html
        assert "Lonely" in html
        assert "RAG explained" not in html
        assert "1 untagged item<" in client.get("/ui/taxonomy").text

    def test_pages_need_login(self, anonymous):
        assert anonymous.get("/ui/taxonomy").status_code == 303
        assert anonymous.post("/ui/taxonomy/tags", data={"path": "x"}).status_code == 303
        assert anonymous.post("/ui/taxonomy/retag").status_code == 303
        assert anonymous.post("/ui/taxonomy/rename", data={"path": "a", "new_path": "b"}).status_code == 303
        assert anonymous.post("/ui/taxonomy/delete", data={"path": "a"}).status_code == 303


def test_static_htmx_is_served(anonymous):
    r = anonymous.get("/static/htmx.min.js")
    assert r.status_code == 200
    assert "htmx" in r.text[:200]


class TestThoughts:
    def write(self, client, **form) -> str:
        r = client.post("/ui/thoughts", data={"title": "", "text": "Soup needs salt.\nMore later.", **form})
        assert r.status_code == 303
        return r.headers["location"].removeprefix("/ui/items/")

    def test_write_form_on_the_list_only(self, client):
        assert 'action="/ui/thoughts"' in client.get("/ui").text
        assert 'action="/ui/thoughts"' not in client.get("/ui/untagged").text

    def test_write_shows_the_thought_with_its_text_and_no_note(self, client, storage):
        iid = self.write(client)
        html = client.get(f"/ui/items/{iid}").text
        assert "<h1>Soup needs salt.</h1>" in html
        assert '<div class="thought-text note">Soup needs salt.\nMore later.</div>' in html
        assert 'class="kind-badge">thought' in html
        assert "+ add a note" not in html
        assert f'action="/ui/items/{iid}/thought"' in html
        assert storage.get_version(storage.get_item(iid).current_version_id).status == "enriched"

    def test_listed_with_a_badge_and_filterable_by_kind(self, client):
        self.write(client)
        html = client.get("/ui").text
        assert "Soup needs salt." in html and "Tomato soup" in html
        assert 'class="kind-badge">thought' in html
        only = client.get("/ui", params={"kind": "thought"}).text
        assert "Soup needs salt." in only and "Tomato soup" not in only
        assert '<option value="thought" selected>' in only
        assert "Tomato soup" in client.get("/ui", params={"kind": "bogus"}).text
        assert "kind=thought" in client.get("/ui/search", params={"kind": "thought"}).text  # carried over in the nav

    def test_empty_text_keeps_the_draft_open(self, client, storage):
        r = client.post("/ui/thoughts", data={"title": "Just a title", "text": " "})
        assert r.status_code == 422
        assert "Text: a Thought needs some text." in r.text
        assert '<details class="write" open>' in r.text
        assert 'value="Just a title"' in r.text
        assert all(i.media_type == "article" for i in storage.items.values())

    def test_edit_adds_a_version(self, client, storage):
        iid = self.write(client, title="Salt")
        assert 'value="Salt"' in client.get(f"/ui/items/{iid}").text  # the form starts from the current Version
        r = client.post(f"/ui/items/{iid}/thought", data={"title": "", "text": "Pepper too."})
        assert (r.status_code, r.headers["location"]) == (303, f"/ui/items/{iid}")
        assert storage.get_item(iid).title == "Pepper too."
        assert len(storage.list_versions(iid)) == 2

    def test_edit_errors(self, client, storage):
        iid = self.write(client)
        r = client.post(f"/ui/items/{iid}/thought", data={"text": ""})
        assert r.status_code == 422 and '<details class="thought-edit" open>' in r.text
        article = item_id(storage, "RAG explained")
        assert client.post(f"/ui/items/{article}/thought", data={"text": "x"}).status_code == 422
        assert client.post("/ui/items/nope/thought", data={"text": "x"}).status_code == 404

    def test_retry_when_nothing_failed_is_409(self, client):
        iid = self.write(client)
        assert client.post(f"/ui/items/{iid}/retry").status_code == 409


class TestDeleteVersion:
    def test_delete_one_version_returns_to_the_item(self, client, storage):
        iid = TestThoughts().write(client)
        client.post(f"/ui/items/{iid}/thought", data={"text": "Second"})
        newest = storage.get_item(iid).current_version_id
        assert f'action="/ui/versions/{quote(newest)}/delete"' in client.get(f"/ui/items/{iid}").text

        r = client.post(f"/ui/versions/{newest}/delete")
        assert (r.status_code, r.headers["location"]) == (303, f"/ui/items/{iid}")
        assert storage.get_item(iid).text == "Soup needs salt.\nMore later."

    def test_the_last_version_has_no_delete_and_is_refused(self, client, storage):
        iid = item_id(storage, "RAG explained")
        assert "Delete this version" not in client.get(f"/ui/items/{iid}").text
        r = client.post(f"/ui/versions/{storage.get_item(iid).current_version_id}/delete")
        assert r.status_code == 409 and "delete the item instead." in r.text
        assert client.post("/ui/versions/nope/delete").status_code == 404
