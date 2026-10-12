import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from kb.app import create_app
from kb.config import MCP_THOUGHT_TEXT_CHARS, Settings
from kb.llm.fake import FakeLLM
from kb.mcp_server import Background, mcp_server
from kb.models import Annotations, CaptureRequest, Channel, Enrichment, Item, Kind, Version, VersionStatus
from kb.pipeline.run import Pipeline
from kb.pipeline.tag import Tagging
from kb.storage.memory import MemoryStorage
from kb.taxonomy import add_tag

SAVED = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def storage():
    s = MemoryStorage()
    for path in ("news", "news/sport", "news/sport/formula1", "cooking"):
        add_tag(s, path, f"About {path}")
    return s


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def background():
    return Background()


@pytest.fixture
def connect(storage, llm, background):
    pipeline = Pipeline(storage, llm)

    @asynccontextmanager
    async def session():
        async with create_connected_server_and_client_session(mcp_server(lambda: pipeline, background)) as client:
            yield client

    return session


async def article(storage, llm, title, tags=(), note="", saved=SAVED) -> Item:
    enrichment = Enrichment(
        title=title,
        summary=f"All about {title}.",
        key_points=["one point"],
        tags=list(tags),
        embedding=await llm.embed(title),
        taxonomy_version=1,
        embedding_model="e",
    )
    version = Version.create(
        CaptureRequest(url=f"https://example.com/{len(storage.items)}", channel=Channel.EXTENSION), saved, "text"
    ).enriched(enrichment)
    storage.put_version(version)
    item = Item.from_version(version).annotated(Annotations(notes=note), enrichment.tags)
    storage.put_item(item)
    return item


async def call(client, tool, **arguments):
    result = await client.call_tool(tool, arguments)
    assert not result.isError, result.content
    return result.structuredContent


async def error(client, tool, **arguments) -> str:
    result = await client.call_tool(tool, arguments)
    assert result.isError
    return result.content[0].text


async def test_lists_the_four_tools(connect):
    async with connect() as client:
        tools = {t.name for t in (await client.list_tools()).tools}
    assert tools == {"search", "write_thought", "tag_item", "list_tags"}


class TestSearch:
    async def test_returns_what_the_search_page_shows(self, connect, storage, llm):
        hamilton = await article(storage, llm, "Hamilton apologises", ["news/sport/formula1"], note="why I kept it")
        await article(storage, llm, "Tomato soup", ["cooking"])
        async with connect() as client:
            found = await call(client, "search", query="Hamilton apologises")

        assert found["semantic"] is True
        first = found["items"][0]
        assert first["item_id"] == hamilton.id
        assert first | {"score": None} == {
            "item_id": hamilton.id,
            "kind": "article",
            "title": "Hamilton apologises",
            "tags": ["news/sport/formula1"],
            "saved_at": "2026-10-01T09:00:00Z",
            "url": "https://example.com/0",
            "score": None,
            "link": f"/ui/items/{hamilton.id}",
            "note": "why I kept it",
            "summary": "All about Hamilton apologises.",
            "key_points": ["one point"],
            "text": "",
        }
        assert first["score"] > found["items"][-1]["score"]

    async def test_filters_like_the_search_page(self, connect, storage, llm):
        f1 = await article(
            storage, llm, "Race report", ["news/sport/formula1"], saved=datetime(2026, 10, 8, tzinfo=UTC)
        )
        await article(storage, llm, "Race report old", ["news/sport/formula1"])
        await article(storage, llm, "Race day soup", ["cooking"], saved=datetime(2026, 10, 8, tzinfo=UTC))
        async with connect() as client:
            found = await call(client, "search", query="race", tag="news/sport", saved_from="2026-10-05")
            thoughts = await call(client, "search", query="race", kind="thought")

        assert [i["item_id"] for i in found["items"]] == [f1.id]
        assert thoughts["items"] == []

    async def test_unknown_tag_points_to_list_tags(self, connect):
        async with connect() as client:
            message = await error(client, "search", query="race", tag="f1")
        assert "list_tags" in message

    async def test_reversed_dates_are_refused(self, connect):
        async with connect() as client:
            message = await error(client, "search", query="race", saved_from="2026-10-05", saved_to="2026-10-01")
        assert "start date is after the end date" in message

    async def test_a_long_thought_is_cut(self, connect, storage, llm, background):
        llm.answers = [Tagging()]
        async with connect() as client:
            await call(client, "write_thought", text="lentils " * MCP_THOUGHT_TEXT_CHARS)
            await background.wait()
            found = await call(client, "search", query="lentils")
        text = found["items"][0]["text"]
        assert len(text) == MCP_THOUGHT_TEXT_CHARS + 1 and text.endswith("…")


class TestWriteThought:
    async def test_shown_at_once_then_enriched_in_the_background(self, connect, storage, llm, background):
        llm.answers = [Tagging(tags=["cooking"])]
        async with connect() as client:
            written = await call(client, "write_thought", text="Soup needs salt.", title="Soup")

            item = storage.get_item(written["item_id"])
            assert (item.media_type, item.title, item.text) == (Kind.THOUGHT, "Soup", "Soup needs salt.")
            assert written["link"] == f"/ui/items/{item.id}"

            await background.wait()
        version = storage.get_version(item.current_version_id)
        assert (version.channel, version.status) == (Channel.MCP, VersionStatus.ENRICHED)
        assert storage.get_item(item.id).tags == ["cooking"]

    async def test_empty_text_is_refused(self, connect, storage):
        async with connect() as client:
            message = await error(client, "write_thought", text="  ")
        assert "needs some text" in message

    async def test_mcp_is_not_a_capture_channel(self):
        with pytest.raises(ValueError, match="written, not captured"):
            CaptureRequest(url="https://example.com", channel=Channel.MCP)


class TestTagItem:
    async def test_adds_an_owner_tag(self, connect, storage, llm):
        item = await article(storage, llm, "Hamilton apologises", ["news/sport"])
        async with connect() as client:
            tagged = await call(client, "tag_item", item_id=item.id, tag="news/sport/formula1")
        assert tagged == {"item_id": item.id, "tags": ["news/sport", "news/sport/formula1"]}
        assert storage.get_item(item.id).annotations.owner_tags == ["news/sport/formula1"]

    async def test_survives_an_enrichment_still_running(self, connect, storage, llm, background):
        llm.answers = [Tagging(tags=["cooking"])]
        gate = asyncio.Event()
        embed = llm.embed

        async def held(text):
            await gate.wait()
            return await embed(text)

        llm.embed = held
        async with connect() as client:
            written = await call(client, "write_thought", text="Soup needs salt.")
            await call(client, "tag_item", item_id=written["item_id"], tag="news")
            assert background.tasks  # the enrichment is still waiting for its embedding
            gate.set()
            await background.wait()
        assert storage.get_item(written["item_id"]).tags == ["cooking", "news"]

    async def test_unknown_tag_points_to_list_tags(self, connect, storage, llm):
        item = await article(storage, llm, "Hamilton apologises")
        async with connect() as client:
            message = await error(client, "tag_item", item_id=item.id, tag="f1")
        assert "list_tags" in message
        assert storage.get_item(item.id).annotations.owner_tags == []

    async def test_unknown_item(self, connect):
        async with connect() as client:
            message = await error(client, "tag_item", item_id="nope", tag="news")
        assert "no item" in message


async def test_list_tags_reads_the_current_taxonomy(connect, storage):
    async with connect() as client:
        before = await call(client, "list_tags")
        add_tag(storage, "ideas", "Half-formed ideas")
        after = await call(client, "list_tags")
    assert {"path": "news/sport/formula1", "description": "About news/sport/formula1"} in before["tags"]
    assert len(after["tags"]) == len(before["tags"]) + 1
    assert {"path": "ideas", "description": "Half-formed ideas"} in after["tags"]


class TestHttp:
    HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

    @pytest.fixture
    def client(self, storage, llm):
        app = create_app(Settings(api_token="secret", _env_file=None), pipeline=Pipeline(storage, llm))
        with TestClient(app, base_url="http://localhost:8000") as client:
            yield client

    def test_mounted_behind_the_bearer_token(self, client):
        r = client.post("/mcp", json=self.LIST, headers=self.HEADERS | {"Authorization": "Bearer secret"})
        assert r.status_code == 200
        assert {t["name"] for t in r.json()["result"]["tools"]} == {"search", "write_thought", "tag_item", "list_tags"}

    @pytest.mark.parametrize("auth", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic secret"}])
    def test_rejects_a_missing_or_wrong_token(self, client, auth):
        assert client.post("/mcp", json=self.LIST, headers=self.HEADERS | auth).status_code == 401

    def test_links_use_the_server_address(self, client, llm):
        llm.answers = [Tagging()]
        call = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "write_thought", "arguments": {"text": "Soup needs salt."}},
        }
        r = client.post("/mcp", json=call, headers=self.HEADERS | {"Authorization": "Bearer secret"})
        written = r.json()["result"]["structuredContent"]
        assert written["link"] == f"http://localhost:8000/ui/items/{written['item_id']}"
