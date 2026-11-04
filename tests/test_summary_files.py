from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kb.models import Agent, Decision, Problem, SessionMeta, SessionRecord, SessionStatus, SessionSummary
from kb.summary_files import ASK, NO_PROJECT, PROJECTS_HEADER, ProjectMap, SummaryFile, parse_body, slug

AT = datetime(2026, 11, 3, 14, 5, 0, tzinfo=UTC)
FULL = dict(
    goal="Import Summary Files.\n\nFrom the host.",
    outcome="Done.",
    decisions=[
        Decision(decision="A host CLI posts the file", reason="Transcripts are on the host", rejected="A mount"),
        Decision(decision="YAML front matter"),
    ],
    problems=[Problem(symptom="422 on import", cause="Project Tag missing", fix="Create it first")],
    dropped=["A file watcher"],
    todo=["The skill"],
    sources=["docs/plan.md"],
    keywords=["POST /sessions", "projects.yaml"],
)


def record(**sections) -> SessionRecord:
    return SessionRecord(
        meta=SessionMeta(
            agent=Agent.CODEX,
            session_id="0a0a0a0a-0000-7000-8000-000000000001",
            folder="/home/owner/project",
            branch="main",
            repo_url="https://github.com/owner/project.git",
            model="gpt-5.6-sol",
            transcript_path="/home/owner/.codex/sessions/rollout.jsonl",
        ),
        summary=SessionSummary(title="Přidat import souhrnů", status=SessionStatus.DONE, **sections),
    )


class TestFormat:
    @pytest.mark.parametrize(
        "summary_file",
        [
            SummaryFile(at=AT, record=record(**FULL), project="project/kb"),
            SummaryFile(at=AT, record=record(goal="Check a link."), project=None),
        ],
        ids=["every section", "small, no Project"],
    )
    def test_a_summary_file_parses_back_exactly(self, summary_file):
        assert SummaryFile.parse(summary_file.render()) == summary_file

    def test_it_reads_as_markdown(self):
        text = SummaryFile(at=AT, record=record(**FULL), project="project/kb").render()
        assert text.startswith("---\nformat: 1\nsummarised_at: '2026-11-03T14:05:00.000Z'\nstatus: done\n")
        assert "\n---\n\n# Přidat import souhrnů\n\n## Goal\n\nImport Summary Files.\n\nFrom the host.\n\n" in text
        assert (
            "## Decisions\n\n- A host CLI posts the file\n  - Reason: Transcripts are on the host\n"
            "  - Rejected: A mount\n- YAML front matter\n\n## Problems\n\n" in text
        )
        assert text.endswith("## Keywords\n\n- POST /sessions\n- projects.yaml\n")

    def test_the_name_is_time_agent_session_and_title(self):
        assert SummaryFile(at=AT, record=record()).name == "2026-11-03-140500-codex-0a0a0a0a-pridat-import-souhrnu.md"

    @pytest.mark.parametrize(
        "body, error",
        [
            ("## Goal\n\nx", "starts with '# <title>'"),
            ("# T\n\nloose text\n\n## Goal\n\nx", "between the title"),
            ("# T\n\n## Goals\n\nx", "unknown or repeated section"),
            ("# T\n\n## Goal\n\nx\n\n## Goal\n\ny", "unknown or repeated section"),
            ("# T\n\n## Decisions\n\n- A\n  - Because: b", "unexpected line"),
            ("# T\n\n## Todo\n\n- A\n  - Reason: b", "unexpected line"),
            ("# T\n\n## Problems\n\nplain text", "unexpected line"),
        ],
    )
    def test_a_body_out_of_shape_is_refused(self, body, error):
        with pytest.raises(ValueError, match=error):
            parse_body(body, "done")

    def test_a_status_is_required(self):
        with pytest.raises(ValidationError):
            parse_body("# T\n\n## Goal\n\nx", None)

    def test_fields_of_an_earlier_shape_are_ignored(self):
        """A file written before usage was dropped (D49) still imports."""
        text = SummaryFile(at=AT, record=record(goal="Check."), project=None).render()
        text = text.replace("---\n\n#", "client: cli\nstarted_at: x\nusage:\n  owner_turns: 3\n---\n\n#")
        assert SummaryFile.parse(text).record == record(goal="Check.")

    @pytest.mark.parametrize(
        "text, error",
        [
            ("# T\n", "front matter"),
            ("---\nformat: 2\n---\n# T\n", "not a Summary File of format 1"),
            ("---\nformat: [\n---\n# T\n", "not valid YAML"),
            ("---\nformat: 1\nproject: kb\n---\n# T\n", "not project/<name>"),
        ],
    )
    def test_a_file_without_front_matter_or_of_another_format_is_refused(self, text, error):
        with pytest.raises(ValueError, match=error):
            SummaryFile.parse(text)

    def test_slug(self):
        assert slug("Přidat import souhrnů!") == "pridat-import-souhrnu"
        assert slug("???") == "session"
        assert len(slug("word " * 30)) <= 50


class TestProjectMap:
    @pytest.fixture
    def projects(self, tmp_path):
        projects = ProjectMap(tmp_path)
        projects.record("/home/owner/sazuu", "project/sazuu")
        projects.record("/home/owner/scratch", NO_PROJECT)
        projects.record("/home/owner", ASK)
        return projects

    @pytest.mark.parametrize(
        "folder, entry",
        [
            ("/home/owner/sazuu", "project/sazuu"),
            ("/home/owner/sazuu/background-agents", "project/sazuu"),
            ("/home/owner/sazuu-old", None),
            ("/home/owner/scratch/x", NO_PROJECT),
            ("/home/owner", ASK),
            ("/home/owner/new-repo", None),  # "ask" covers only the folder itself
        ],
    )
    def test_lookup(self, projects, folder, entry):
        assert projects.lookup(folder) == entry

    def test_it_is_kept_in_the_folder(self, projects, tmp_path):
        assert ProjectMap(tmp_path).folders == projects.folders
        assert projects.path.read_text(encoding="utf-8").startswith(PROJECTS_HEADER)

    def test_a_value_is_a_project_none_or_ask(self, projects):
        with pytest.raises(ValueError, match="not project/<name>"):
            projects.record("/home/owner/x", "sazuu")
