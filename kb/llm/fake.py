"""Deterministic LLM for tests: returns the given answers and hash-derived embeddings."""

import hashlib

from pydantic import BaseModel

from kb.config import EMBEDDING_DIM


class FakeLLM:
    def __init__(self, answers: list[BaseModel] | None = None) -> None:
        self.model = "fake-llm"
        self.embedding_model = "fake-embedding"
        self.answers = list(answers or [])
        self.calls: list[tuple[str, str]] = []
        self.embedded: list[str] = []

    async def structured[T: BaseModel](self, system: str, user: str, schema: type[T]) -> T:
        self.calls.append((system, user))
        answer = self.answers.pop(0)
        if not isinstance(answer, schema):
            raise TypeError(f"expected {schema.__name__}, got {type(answer).__name__}")
        return answer

    async def embed(self, text: str) -> list[float]:
        self.embedded.append(text)
        digest = hashlib.sha256(text.encode()).digest()
        return [(digest[i % len(digest)] + 1) / 256 for i in range(EMBEDDING_DIM)]
