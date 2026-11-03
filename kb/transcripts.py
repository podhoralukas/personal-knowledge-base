"""Reading an agent's Transcript for what code can tell about a Session (D43): where and when it ran, which
models it used and how much. The conversation itself is never read.

`Transcript` holds what every agent has in common; each agent's format is a subclass. Another agent is another
subclass (and a value of `Agent`): `Transcript.read` tries every subclass."""

import json
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from kb.models import Agent, ModelUsage, SessionMeta, SessionUsage

# Our token fields: input excludes cache reads, thinking is part of the output (as in `ModelUsage`).
TOKEN_FIELDS = ("input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens", "cache_write_tokens")


class Transcript(ABC):
    """One Session's Transcript. A subclass says whether events are its agent's, and its constructor reads from
    them every fact below."""

    agent: ClassVar[Agent]
    _formats: ClassVar[list[type["Transcript"]]] = []

    session_id: str
    client: str = ""  # the agent's own name for where it ran, e.g. its VS Code extension
    folder: str = ""
    branch: str = ""
    repo_url: str = ""
    tokens: dict[str, Counter]  # per model, a Counter over `TOKEN_FIELDS`
    owner_turns: int
    tool_calls: int
    cost_usd: float | None = None  # only where the agent reports it; we keep no price table

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        Transcript._formats.append(cls)

    def __init__(self, events: list[dict], path: str = "") -> None:
        if not self.recognises(events):
            raise ValueError(f"not a {self.agent} transcript")
        self.path = path
        times = [datetime.fromisoformat(e["timestamp"]) for e in events if e.get("timestamp")]
        self.started_at = min(times, default=None)
        self.ended_at = max(times, default=None)

    @classmethod
    @abstractmethod
    def recognises(cls, events: list[dict]) -> bool: ...

    @classmethod
    def read(cls, path: Path) -> "Transcript":
        """The Transcript at `path`, in the format of whichever agent recognises it."""
        with path.open(encoding="utf-8") as f:
            events = list(parse(f))
        for agent_format in cls._formats:
            if agent_format.recognises(events):
                return agent_format(events, str(path))
        raise ValueError(f"not a transcript of a known agent: {path}")

    @property
    def meta(self) -> SessionMeta:
        return SessionMeta(
            agent=self.agent,
            session_id=self.session_id,
            client=self.client,
            folder=self.folder,
            branch=self.branch,
            repo_url=self.repo_url,
            transcript_path=self.path,
            started_at=self.started_at,
            ended_at=self.ended_at,
        )

    @property
    def usage(self) -> SessionUsage:
        return SessionUsage(
            models=[ModelUsage(model=model, **tokens) for model, tokens in sorted(self.tokens.items())],
            owner_turns=self.owner_turns,
            tool_calls=self.tool_calls,
            cost_usd=self.cost_usd,
        )


def parse(lines: Iterable[str]) -> Iterator[dict]:
    """The events, skipping a line that is not JSON: the agent may still be writing the last one."""
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


class ClaudeCodeTranscript(Transcript):
    """`~/.claude/projects/<folder>/<session id>.jsonl`. Each Claude Code process writes a cumulative
    `cost-state` for its part of the Session when it exits; it also counts background calls the messages do not
    show. Tokens and cost come from those when they cover the messages. They do not while the Session is still
    running (the usual moment for a summary) or after a process was killed: then the tokens come from the
    messages and the cost is unknown. Subagents' Transcripts (`<session id>/subagents/`) are not read."""

    agent = Agent.CLAUDE_CODE

    # Claude Code's names for our token fields, in `cost-state` and in a message's usage.
    COST_STATE_FIELDS = (
        "inputTokens",
        "outputTokens",
        "thinkingTokens",
        "cacheReadInputTokens",
        "cacheCreationInputTokens",
    )
    MESSAGE_FIELDS = (
        "input_tokens",
        "output_tokens",
        "thinking_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    # A cost-state a few tokens short of the messages still covers them (seen: up to 16 tokens in 100k).
    COST_STATE_COVERAGE = 0.99

    @classmethod
    def recognises(cls, events: list[dict]) -> bool:
        return any(e.get("type") in ("user", "assistant") and e.get("sessionId") for e in events)

    def __init__(self, events: list[dict], path: str = "") -> None:
        super().__init__(events, path)
        messages = [e for e in events if e.get("type") in ("user", "assistant")]
        first = messages[0]
        self.session_id = first["sessionId"]
        self.client = first.get("entrypoint", "")
        self.folder = first.get("cwd", "")
        # The last one: the Owner may switch branch during a Session.
        self.branch = next((b for e in reversed(messages) if (b := e.get("gitBranch"))), "")
        # Prompts the Owner typed; not tool results, interruptions, slash-command output or skill bodies.
        self.owner_turns = sum(
            e["type"] == "user" and e.get("turnOrigin") == "human" and not e.get("isSidechain") for e in messages
        )
        assistant = [e["message"] for e in messages if e["type"] == "assistant"]
        self.tool_calls = len(
            {b["id"] for m in assistant for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"}
        )

        processes = {e["startTime"]: e for e in events if e.get("type") == "cost-state"}  # the last one of each
        reported = defaultdict(Counter)
        for state in processes.values():
            for model, u in state["modelUsage"].items():
                reported[model] += _named(u, self.COST_STATE_FIELDS)
        # One API response is split into an event per content block; each carries the response's usage.
        seen = defaultdict(Counter)
        for m in {m["id"]: m for m in assistant}.values():
            if m["model"] != "<synthetic>":  # Claude Code's own error notices, no API call
                seen[m["model"]] += _named(
                    m["usage"] | (m["usage"].get("output_tokens_details") or {}), self.MESSAGE_FIELDS
                )
        covered = bool(processes) and all(
            reported[model]["output_tokens"] >= self.COST_STATE_COVERAGE * tokens["output_tokens"]
            for model, tokens in seen.items()
        )
        self.tokens = reported if covered else seen
        self.cost_usd = sum(s["totalCostUSD"] for s in processes.values()) if covered else None


class CodexTranscript(Transcript):
    """`~/.codex/sessions/<yyyy>/<mm>/<dd>/rollout-<time>-<session id>.jsonl`. Tokens per model from
    `token_usage_record` (one per response, with its turn, whose model `turn_context` names); older rollouts have
    only the cumulative `token_count`, whose growth goes to the current turn's model. Codex reports no cost."""

    agent = Agent.CODEX

    TOOL_CALLS = ("function_call", "custom_tool_call", "web_search_call", "tool_search_call")

    @classmethod
    def recognises(cls, events: list[dict]) -> bool:
        return bool(events) and events[0].get("type") == "session_meta"

    def __init__(self, events: list[dict], path: str = "") -> None:
        super().__init__(events, path)
        session = events[0]["payload"]
        git = session.get("git") or {}
        self.session_id = session["id"]
        self.client = session.get("originator", "")
        self.folder = session.get("cwd", "")
        self.branch = git.get("branch") or ""
        self.repo_url = git.get("repository_url") or ""

        per_record = any(e.get("type") == "token_usage_record" for e in events)
        turn_models, model, counted = {}, None, {}
        self.tokens = defaultdict(Counter)
        self.owner_turns = self.tool_calls = 0
        for e in events:
            kind, p = e.get("type"), e.get("payload") or {}
            message = p.get("type") if kind == "event_msg" else None
            if kind == "turn_context":
                turn_models[p["turn_id"]] = model = p["model"]
            elif kind == "token_usage_record":
                self.tokens[turn_models.get(p["turn_id"], model)] += _openai_tokens(p["usage"])
            elif message == "token_count" and p.get("info") and not per_record:
                total = p["info"]["total_token_usage"]  # its last one can lag behind the records
                self.tokens[model] += _openai_tokens({k: v - counted.get(k, 0) for k, v in total.items()})
                counted = total
            elif message == "item_completed" and p["item"].get("type") == "UserMessage":
                # Also one sent during a turn; a `role: user` message also carries injected context.
                self.owner_turns += 1
            elif kind == "response_item" and p.get("type") in self.TOOL_CALLS:
                self.tool_calls += 1


def _named(usage: dict, names: tuple[str, ...]) -> Counter:
    """`usage` under our field names, given the agent's name for each."""
    return Counter({ours: usage.get(theirs, 0) for ours, theirs in zip(TOKEN_FIELDS, names, strict=True)})


def _openai_tokens(u: dict) -> Counter:
    """OpenAI counts cached input inside the input; ours, like Anthropic's, does not."""
    cached = u.get("cached_input_tokens", 0)
    return Counter(
        {
            "input_tokens": u.get("input_tokens", 0) - cached,
            "output_tokens": u.get("output_tokens", 0),
            "thinking_tokens": u.get("reasoning_output_tokens", 0),
            "cache_read_tokens": cached,
            "cache_write_tokens": u.get("cache_write_input_tokens", 0),
        }
    )
