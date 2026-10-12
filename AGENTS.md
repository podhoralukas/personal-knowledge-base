See [README.md](README.md) for project overview, setup instructions, and configuration.

## Paid LLM APIs

- **pytest is offline.** Every LLM response in a test is mocked: `kb.llm.fake.FakeLLM` for pipeline and app tests, `httpx.MockTransport` behind `AsyncOpenAI` for `LLMClient` itself (see `tests/test_llm.py`). Write new tests the same way. As a backstop, `tests/conftest.py` replaces the API keys from `.env` with a fake one.
- **Outside pytest, ask first.** Any real call to OpenAI, Anthropic or another paid provider (an ad-hoc script, a running app with a real key) needs the owner's explicit permission in the current conversation, each time. Say exactly what you would run.
- Integration tests against real providers do not exist yet; if they are added, they stay out of the default pytest run.

## Code style

- **No annotations on local variables.** Write `keyword = {...}`, not `keyword: dict = {...}`. Annotate function signatures and class fields only.
