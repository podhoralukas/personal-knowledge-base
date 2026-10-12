import pytest


@pytest.fixture(autouse=True)
def no_real_llm_keys(monkeypatch):
    """Override any key from .env so a stray real API call is rejected instead of billed."""
    for name in ("LLM_API_KEY", "EMBEDDING_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(name, "test-key-not-real")
