"""The Transcript reader, on synthetic Transcripts shaped like real ones (Claude Code 2.1, Codex 0.154): only the
fields the reader uses, every text "…", made-up ids, times and token counts."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from kb.models import Agent, ModelUsage
from kb.transcripts import ClaudeCodeTranscript, CodexTranscript, Transcript, parse

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"
CLAUDE_CODE = FIXTURES / "claude-code.jsonl"
CODEX = FIXTURES / "codex.jsonl"

# The five opus responses of the Claude Code fixture, each counted once.
OPUS = ModelUsage(
    model="claude-opus-5-5",
    input_tokens=6,
    output_tokens=800,
    thinking_tokens=200,
    cache_read_tokens=8800,
    cache_write_tokens=600,
)


def events(path: Path) -> list[dict]:
    return list(parse(path.read_text(encoding="utf-8").splitlines()))


class TestClaudeCode:
    def test_metadata(self):
        meta = Transcript.read(CLAUDE_CODE).meta
        assert meta.model_dump() == {
            "agent": Agent.CLAUDE_CODE,
            "session_id": "c0ffee00-0000-4000-8000-000000000001",
            "client": "claude-vscode",
            "folder": "/home/owner/project",
            "branch": "feature/search",  # the last one: the Owner switched branch during the Session
            "repo_url": "",
            "transcript_path": str(CLAUDE_CODE),
            "started_at": datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC),
            "ended_at": datetime(2026, 1, 5, 9, 21, 0, tzinfo=UTC),
        }

    def test_turns_are_the_owners_prompts_and_tool_calls_are_counted_once(self):
        """Not counted as turns: tool results, an interruption, a meta message."""
        usage = Transcript.read(CLAUDE_CODE).usage
        assert (usage.owner_turns, usage.tool_calls) == (4, 3)

    def test_usage_is_the_last_cost_state_of_each_process_added_up(self):
        """Process 1000 wrote two cumulative cost-states; process 2000 also made a background haiku call."""
        usage = Transcript.read(CLAUDE_CODE).usage
        assert usage.models == [ModelUsage(model="claude-haiku-5-5", input_tokens=900, output_tokens=20), OPUS]
        assert usage.cost_usd == pytest.approx(0.30)

    @pytest.mark.parametrize(
        "cost_states",
        [
            pytest.param([], id="still running"),
            pytest.param(
                [{"type": "cost-state", "startTime": 1, "totalCostUSD": 0, "modelUsage": {}}], id="an idle process"
            ),
        ],
    )
    def test_without_a_covering_cost_state_the_tokens_come_from_each_response_once(self, cost_states):
        """The cost is then unknown. A response split into two events counts once; the `<synthetic>` notice
        made no call."""
        usage = ClaudeCodeTranscript([e for e in events(CLAUDE_CODE) if e["type"] != "cost-state"] + cost_states).usage
        assert (usage.models, usage.cost_usd) == ([OPUS], None)


class TestCodex:
    def test_metadata(self):
        meta = Transcript.read(CODEX).meta
        assert meta.model_dump() == {
            "agent": Agent.CODEX,
            "session_id": "0a0a0a0a-0000-7000-8000-000000000001",
            "client": "codex_vscode",
            "folder": "/home/owner/project",
            "branch": "main",
            "repo_url": "https://github.com/owner/project.git",
            "transcript_path": str(CODEX),
            "started_at": datetime(2026, 1, 6, 10, 0, 0, tzinfo=UTC),
            "ended_at": datetime(2026, 1, 6, 10, 30, 0, tzinfo=UTC),
        }

    def test_tokens_per_model_from_the_records_of_each_turn(self):
        """The model changed between the turns; cached input is moved out of the input. A message sent during
        turn 2 is a turn of the Owner's; a user message with injected context is not."""
        usage = Transcript.read(CODEX).usage
        assert usage.models == [
            ModelUsage(
                model="gpt-5.6-luna", input_tokens=400, output_tokens=150, thinking_tokens=50, cache_read_tokens=1800
            ),
            ModelUsage(
                model="gpt-5.6-sol", input_tokens=1500, output_tokens=460, thinking_tokens=200, cache_read_tokens=2000
            ),
        ]
        assert (usage.owner_turns, usage.tool_calls, usage.cost_usd) == (3, 3, None)

    def test_an_older_rollout_counts_the_growth_of_token_count(self):
        """token_count lags: the last response is not in it yet."""
        older = [e for e in events(CODEX) if e["type"] != "token_usage_record"]
        luna, sol = CodexTranscript(older).usage.models
        assert luna == Transcript.read(CODEX).usage.models[0]
        assert sol == ModelUsage(
            model="gpt-5.6-sol", input_tokens=1000, output_tokens=400, thinking_tokens=200, cache_read_tokens=2000
        )


def test_a_line_still_being_written_is_skipped(tmp_path):
    path = tmp_path / "session.jsonl"
    path.write_text(CODEX.read_text(encoding="utf-8") + '{"type": "event_msg", "payl', encoding="utf-8")
    assert Transcript.read(path).usage == Transcript.read(CODEX).usage


def test_a_file_that_is_no_transcript_is_refused(tmp_path):
    path = tmp_path / "other.jsonl"
    path.write_text('{"type": "summary"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="known agent"):
        Transcript.read(path)


def test_each_agent_reads_only_its_own_format():
    with pytest.raises(ValueError, match="not a codex transcript"):
        CodexTranscript(events(CLAUDE_CODE))
