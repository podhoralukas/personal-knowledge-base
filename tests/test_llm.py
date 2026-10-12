import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from kb.config import EMBEDDING_DIM, Settings
from kb.llm import LLMClient
from kb.llm.fake import FakeLLM


class Answer(BaseModel):
    city: str
    country: str


class TestFakeLLM:
    async def test_returns_answers_in_order_and_records_calls(self):
        fake = FakeLLM(answers=[Answer(city="Brno", country="CZ")])
        answer = await fake.structured("sys", "where?", Answer)
        assert answer.city == "Brno"
        assert fake.calls == [("sys", "where?")]

    async def test_rejects_answer_of_wrong_schema(self):
        class Other(BaseModel):
            x: int

        fake = FakeLLM(answers=[Other(x=1)])
        with pytest.raises(TypeError):
            await fake.structured("sys", "q", Answer)

    async def test_embedding_is_deterministic_and_non_zero(self):
        fake = FakeLLM()
        a, b = await fake.embed("hello"), await fake.embed("hello")
        assert a == b
        assert len(a) == EMBEDDING_DIM
        assert all(v > 0 for v in a)
        assert await fake.embed("other") != a


class TestSettings:
    def test_openai_api_key_is_accepted_for_both_endpoints(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "k1")
        s = Settings(_env_file=None)
        assert (s.llm_api_key, s.embedding_api_key) == ("k1", "k1")

    def test_embedding_endpoint_can_differ(self, monkeypatch):
        monkeypatch.setenv("LLM_BASE_URL", "https://api.anthropic.com/v1/")
        monkeypatch.setenv("LLM_API_KEY", "anthropic")
        monkeypatch.setenv("EMBEDDING_API_KEY", "openai")
        s = Settings(_env_file=None)
        client = LLMClient.from_settings(s)
        assert str(client.chat.base_url) == "https://api.anthropic.com/v1/"
        assert str(client.embeddings.base_url) == "https://api.openai.com/v1/"
        assert (client.chat.api_key, client.embeddings.api_key) == ("anthropic", "openai")


def mocked_client(responses: dict[str, dict], requests: list[httpx.Request]) -> LLMClient:
    """LLMClient whose HTTP traffic is answered from `responses`, keyed by URL path suffix."""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        suffix = next(k for k in responses if request.url.path.endswith(k))
        return httpx.Response(200, json=responses[suffix])

    def openai(base_url: str) -> AsyncOpenAI:
        transport = httpx.MockTransport(handler)
        return AsyncOpenAI(base_url=base_url, api_key="test", http_client=httpx.AsyncClient(transport=transport))

    return LLMClient(openai("http://chat.test/v1"), "chat-model", openai("http://embed.test/v1"), "embed-model")


def completion(content: str | None, refusal: str | None = None) -> dict:
    message = {"role": "assistant", "content": content, "refusal": refusal}
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "chat-model",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
    }


class TestLLMClient:
    async def test_structured_sends_schema_and_parses_answer(self):
        requests = []
        client = mocked_client({"/chat/completions": completion('{"city": "Prague", "country": "CZ"}')}, requests)

        answer = await client.structured("Answer with the capital city.", "Czech Republic", Answer)

        assert answer == Answer(city="Prague", country="CZ")
        (request,) = requests
        assert request.url.host == "chat.test"
        body = json.loads(request.content)
        assert body["model"] == "chat-model"
        assert body["temperature"] == 0
        assert body["messages"] == [
            {"role": "system", "content": "Answer with the capital city."},
            {"role": "user", "content": "Czech Republic"},
        ]
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["schema"]["required"] == ["city", "country"]

    async def test_refusal_raises(self):
        client = mocked_client({"/chat/completions": completion(None, refusal="I can't help with that.")}, [])
        with pytest.raises(RuntimeError, match="I can't help with that."):
            await client.structured("sys", "q", Answer)

    async def test_embed_uses_the_embedding_endpoint(self):
        requests = []
        response = {
            "object": "list",
            "model": "embed-model",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.25] * EMBEDDING_DIM}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }
        client = mocked_client({"/embeddings": response}, requests)

        vector = await client.embed("hello")

        assert vector == [0.25] * EMBEDDING_DIM
        (request,) = requests
        assert request.url.host == "embed.test"
        assert json.loads(request.content)["model"] == "embed-model"
        assert json.loads(request.content)["input"] == "hello"
