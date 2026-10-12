"""LLM seam: one structured-output call and one embedding call over any OpenAI-compatible endpoint."""

from typing import Protocol

from openai import AsyncOpenAI
from pydantic import BaseModel

from kb.config import LLM_TEMPERATURE, Settings


class LLM(Protocol):
    model: str
    embedding_model: str

    async def structured[T: BaseModel](self, system: str, user: str, schema: type[T]) -> T: ...

    async def embed(self, text: str) -> list[float]: ...


class LLMClient:
    def __init__(self, chat: AsyncOpenAI, model: str, embeddings: AsyncOpenAI, embedding_model: str) -> None:
        self.chat = chat
        self.model = model
        self.embeddings = embeddings
        self.embedding_model = embedding_model

    @classmethod
    def from_settings(cls, s: Settings) -> "LLMClient":
        return cls(
            chat=AsyncOpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key),
            model=s.llm_model,
            embeddings=AsyncOpenAI(base_url=s.embedding_base_url, api_key=s.embedding_api_key),
            embedding_model=s.embedding_model,
        )

    async def structured[T: BaseModel](self, system: str, user: str, schema: type[T]) -> T:
        completion = await self.chat.chat.completions.parse(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=schema,
            temperature=LLM_TEMPERATURE,
        )
        message = completion.choices[0].message
        if message.parsed is None:
            raise RuntimeError(f"no structured output from {self.model}: {message.refusal or 'empty response'}")
        return message.parsed

    async def embed(self, text: str) -> list[float]:
        response = await self.embeddings.embeddings.create(model=self.embedding_model, input=text)
        return response.data[0].embedding
