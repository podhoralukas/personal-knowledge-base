"""Saving Session Summaries: the app writes the Summary File into the folder mounted from the host, then stores
the Version (ADR-0005). What it knows about a Session comes from the agent; a Transcript is never read."""

from datetime import UTC, datetime
from pathlib import Path

from kb.models import SessionRecord, Version
from kb.normalize import session_item_id
from kb.pipeline.run import Pipeline
from kb.storage import Storage
from kb.summary_files import ASK, NO_PROJECT, ProjectMap, SummaryFile, check_project
from kb.taxonomy import add_tag


class NoProject(ValueError):
    """The Session's folder has no Project yet, or asks every time: the Owner has to choose."""


def save_summary(
    pipeline: Pipeline,
    folder: Path,
    record: SessionRecord,
    project: str | None = None,
    always_ask: bool = False,
    at: datetime | None = None,
) -> Version:
    """A new Version of the Session, shown at once; the embedding follows. The same summary as the newest Version
    returns that Version, so a retry leaves no duplicate. `project` is the Owner's answer for a folder the mapping
    does not decide, recorded for a new folder; `always_ask` records that the folder asks every time instead."""
    item_id = session_item_id(record.meta.agent, record.meta.session_id)
    newest = next(iter(pipeline.storage.list_versions(item_id)), None)
    if newest is not None and newest.session.summary == record.summary:
        return pipeline.session(newest.session, newest.captured_at)  # pending again if its embedding failed

    session_folder = record.meta.folder
    projects = ProjectMap(folder)
    known = projects.lookup(session_folder)
    if project is None and known in (None, ASK):
        raise NoProject(
            f"{session_folder} has no Project: ask the Owner (a project/ Tag from list_tags, a new project/<name>, "
            f"or {NO_PROJECT}), then call again with `project`"
        )
    chosen = project or known
    check_project(chosen)
    summary_file = SummaryFile(
        at=at or datetime.now(UTC), record=record, project=None if chosen == NO_PROJECT else chosen
    )
    text = summary_file.render()
    if SummaryFile.parse(text).record != record:
        raise ValueError("this summary would not read back from its file: keep each list item on one line")

    if always_ask:
        projects.record(session_folder, ASK)
    elif known is None:
        projects.record(session_folder, chosen)
    with (folder / summary_file.name).open("x", encoding="utf-8") as f:  # never rewritten
        f.write(text)
    return _stored(pipeline, summary_file)


def import_folder(pipeline: Pipeline, folder: Path) -> tuple[list[Version], list[tuple[str, str]]]:
    """Store every Summary File in `folder` the knowledge base does not have (D54). Returns the Version of each
    file, those to embed being pending, and the files that failed, each with why."""
    versions, failed = [], []
    for path in sorted(folder.glob("*.md")):
        try:
            versions.append(_stored(pipeline, SummaryFile.parse(path.read_text(encoding="utf-8"))))
        except ValueError as exc:
            failed.append((path.name, str(exc)))
    return versions, failed


def _stored(pipeline: Pipeline, summary_file: SummaryFile) -> Version:
    project = summary_file.project
    if project:
        _ensure_tags(pipeline.storage, project)
    return pipeline.session(summary_file.record, summary_file.at, [project] if project else [])


def _ensure_tags(storage: Storage, project: str) -> None:
    """The Project's Tag and its parents, created if missing: the Owner chose it (D52)."""
    taxonomy = storage.get_taxonomy()
    parts = project.split("/")
    for depth in range(1, len(parts) + 1):
        path = "/".join(parts[:depth])
        if taxonomy.get(path) is None:
            add_tag(storage, path)
