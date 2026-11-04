"""Summary Files (ADR-0005): one Markdown file per Version of a Session, the record the knowledge base can be
rebuilt from. The front matter identifies the Session; the body holds the agent's sections, in a fixed shape that
reads well in any notes app and parses back exactly. The folder also holds the folder → Project mapping (D44)."""

import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel

from kb.config import TAG_PATH_PATTERN
from kb.models import Decision, Problem, SessionMeta, SessionRecord, SessionSummary
from kb.normalize import format_captured_at

FORMAT = 1
FILE_SLUG_CHARS = 50
SECTIONS = ("Goal", "Outcome", "Decisions", "Problems", "Dropped", "Todo", "Sources", "Keywords")
# The labelled sub-bullets under a Decision or a Problem, and the fields they fill.
LABELS = {
    "Decisions": {"Reason": "reason", "Rejected": "rejected"},
    "Problems": {"Cause": "cause", "Fix": "fix"},
}

PROJECTS_FILE = "projects.yaml"
NO_PROJECT = "none"
ASK = "ask"
PROJECTS_HEADER = """\
# Folder -> Project of the Session Summaries written in it. A value is a Tag under project/, "none" (no
# Project) or "ask" (ask every time). A Project or "none" also covers the folder's sub-folders; "ask" only
# the folder itself.
"""


class SummaryFile(BaseModel):
    """A Session Summary as written at `at`, with the Session's Project (a Tag under `project/`, or None)."""

    at: datetime
    record: SessionRecord
    project: str | None = None

    @property
    def name(self) -> str:
        """`<date>-<time>-<agent>-<session id start>-<title>.md`: one per Version, sorted by time."""
        meta = self.record.meta
        when = self.at.astimezone(UTC).strftime("%Y-%m-%d-%H%M%S")
        return f"{when}-{meta.agent}-{meta.session_id[:8]}-{slug(self.record.summary.title)}.md"

    def render(self) -> str:
        r = self.record
        front = {
            "format": FORMAT,
            "summarised_at": format_captured_at(self.at),
            "status": r.summary.status.value,
            "project": self.project or NO_PROJECT,
            "after_the_fact": r.after_the_fact,
            **r.meta.model_dump(mode="json"),
        }
        return f"---\n{yaml.safe_dump(front, sort_keys=False, allow_unicode=True)}---\n\n{render_body(r.summary)}"

    @classmethod
    def parse(cls, text: str) -> "SummaryFile":
        """Raises ValueError (pydantic's included) for anything that is not a Summary File of this format."""
        match = re.fullmatch(r"---\n(.*?)\n---\n(.*)", text.replace("\r\n", "\n"), re.DOTALL)
        if match is None:
            raise ValueError("a Summary File starts with front matter between '---' lines")
        try:
            front = yaml.safe_load(match[1])
        except yaml.YAMLError as exc:
            raise ValueError(f"the front matter is not valid YAML: {exc}")
        if not isinstance(front, dict) or front.get("format") != FORMAT:
            raise ValueError(f"not a Summary File of format {FORMAT}")
        project = front.get("project", NO_PROJECT)
        check_project(project)
        record = SessionRecord(
            meta=SessionMeta(**{k: v for k, v in front.items() if k in SessionMeta.model_fields}),
            summary=parse_body(match[2], front.get("status")),
            after_the_fact=front.get("after_the_fact", False),
        )
        return cls(at=front.get("summarised_at"), record=record, project=None if project == NO_PROJECT else project)


def render_body(s: SessionSummary) -> str:
    sections = {
        "Goal": [s.goal] if s.goal else [],
        "Outcome": [s.outcome] if s.outcome else [],
        "Decisions": [_item(d.decision, {"Reason": d.reason, "Rejected": d.rejected}) for d in s.decisions],
        "Problems": [_item(p.symptom, {"Cause": p.cause, "Fix": p.fix}) for p in s.problems],
        **{h: [f"- {line}" for line in getattr(s, h.lower())] for h in ("Dropped", "Todo", "Sources", "Keywords")},
    }
    blocks = [f"# {s.title}", *(f"## {h}\n\n" + "\n".join(lines) for h, lines in sections.items() if lines)]
    return "\n\n".join(blocks) + "\n"


def parse_body(body: str, status: str) -> SessionSummary:
    """The agent's part: `# title`, then `## <section>` in any order. Goal and Outcome are text; every other
    section is `- ` bullets, a Decision or a Problem with `  - <Label>: <text>` sub-bullets."""
    lines = body.strip().split("\n")
    if not lines[0].startswith("# "):
        raise ValueError("the body starts with '# <title>'")
    sections = {}
    current = None
    for line in lines[1:]:
        if line.startswith("## "):
            current = line[3:].strip()
            if current not in SECTIONS or current in sections:
                raise ValueError(f"unknown or repeated section {current!r}; the sections are {', '.join(SECTIONS)}")
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
        elif line.strip():
            raise ValueError("text between the title and the first '## ' section")

    fields = {"title": lines[0][2:].strip(), "status": status}
    for heading, section in sections.items():
        if heading in ("Goal", "Outcome"):
            fields[heading.lower()] = "\n".join(section).strip()
            continue
        items = _bullets(heading, section)
        if heading == "Decisions":
            fields["decisions"] = [Decision(decision=head, **labels) for head, labels in items]
        elif heading == "Problems":
            fields["problems"] = [Problem(symptom=head, **labels) for head, labels in items]
        else:
            fields[heading.lower()] = [head for head, _ in items]
    return SessionSummary(**fields)


def _item(head: str, labels: dict[str, str]) -> str:
    return "\n".join([f"- {head}", *(f"  - {label}: {text}" for label, text in labels.items() if text)])


def _bullets(heading: str, lines: list[str]) -> list[tuple[str, dict[str, str]]]:
    items = []
    for line in lines:
        if not line.strip():
            continue
        if line.startswith("- "):
            items.append((line[2:].strip(), {}))
            continue
        label, sep, text = line.removeprefix("  - ").partition(": ")
        field = LABELS.get(heading, {}).get(label)
        if not line.startswith("  - ") or not sep or field is None or not items:
            raise ValueError(f"{heading}: unexpected line {line.strip()!r}")
        items[-1][1][field] = text.strip()
    return items


def slug(title: str) -> str:
    """The title in lowercase ASCII words joined by '-', for a file name."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    return words[:FILE_SLUG_CHARS].rstrip("-") or "session"


def check_project(value: str) -> None:
    if value != NO_PROJECT and not re.fullmatch(f"project/{TAG_PATH_PATTERN}", str(value)):
        raise ValueError(f"{value!r} is not project/<name> or {NO_PROJECT!r}")


class ProjectMap:
    """`projects.yaml` in the Summary File folder: for a folder, its Project (a Tag under `project/`), `none`
    or `ask`. Personal, so it lives with the summaries and never in this repo."""

    def __init__(self, folder: Path) -> None:
        self.path = folder / PROJECTS_FILE
        self.folders = (yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}) if self.path.exists() else {}

    def lookup(self, folder: str) -> str | None:
        """The entry that covers `folder`: a Project, `none` or `ask`; None for a folder not seen before."""
        if self.folders.get(folder) == ASK:
            return ASK
        covering = [f for f, v in self.folders.items() if v != ASK and (folder == f or folder.startswith(f"{f}/"))]
        return self.folders[max(covering, key=len)] if covering else None

    def record(self, folder: str, value: str) -> None:
        if value != ASK:
            check_project(value)
        self.folders[folder] = value
        self.save()

    def save(self) -> None:
        mapping = yaml.safe_dump(dict(sorted(self.folders.items())), allow_unicode=True)
        self.path.write_text(PROJECTS_HEADER + mapping, encoding="utf-8")
