"""Saving a Session Summary into the folder, and rebuilding from the folder through POST /sessions/import."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from kb.app import create_app
from kb.config import Settings
from kb.llm.fake import FakeLLM
from kb.models import Agent, Decision, SessionMeta, SessionRecord, SessionStatus, SessionSummary, VersionStatus
from kb.normalize import session_item_id
from kb.pipeline.run import Pipeline
from kb.sessions import NoProject, save_summary
from kb.storage.memory import MemoryStorage
from kb.summary_files import ASK, ProjectMap

FOLDER = "/home/owner/project"
SESSION = session_item_id(Agent.CLAUDE_CODE, "c0ffee00")
AUTH = {"Authorization": "Bearer secret"}
T1 = datetime(2026, 11, 3, 14, 5, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 3, 16, 0, 0, tzinfo=UTC)


class FailingLLM(FakeLLM):
    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding service down")


def record(goal="Read usage.", decision="Classes per agent") -> SessionRecord:
    return SessionRecord(
        meta=SessionMeta(agent=Agent.CLAUDE_CODE, session_id="c0ffee00", folder=FOLDER, branch="main"),
        summary=SessionSummary(
            title="Transcript reader",
            status=SessionStatus.DONE,
            goal=goal,
            decisions=[Decision(decision=decision, reason="Pi may come")],
        ),
    )


@pytest.fixture
def storage():
    return MemoryStorage()


@pytest.fixture
def pipeline(storage):
    return Pipeline(storage, FakeLLM())


def summary_files(folder):
    return sorted(p.name for p in folder.glob("*.md"))


class TestSave:
    def test_a_new_folder_needs_the_owners_answer(self, pipeline, tmp_path):
        with pytest.raises(NoProject, match=f"{FOLDER} has no Project"):
            save_summary(pipeline, tmp_path, record(), at=T1)
        assert summary_files(tmp_path) == []
        assert ProjectMap(tmp_path).lookup(FOLDER) is None

    async def test_the_answer_is_recorded_and_the_summary_stored_from_its_file(self, pipeline, storage, tmp_path):
        version = save_summary(pipeline, tmp_path, record(), project="project/kb", at=T1)

        assert summary_files(tmp_path) == ["2026-11-03-140500-claude-code-c0ffee00-transcript-reader.md"]
        assert ProjectMap(tmp_path).lookup(FOLDER) == "project/kb"
        assert {t.path for t in storage.get_taxonomy().tags} == {"project", "project/kb"}
        item = storage.get_item(SESSION)
        assert (item.title, item.tags) == ("Transcript reader", ["project/kb"])
        assert (await pipeline.enrich(version)).status is VersionStatus.ENRICHED

    def test_the_next_summary_of_the_folder_takes_its_project_from_the_mapping(self, pipeline, storage, tmp_path):
        save_summary(pipeline, tmp_path, record(), project="project/kb", at=T1)
        save_summary(pipeline, tmp_path, record(goal="Read more."), at=T2)
        assert len(storage.list_versions(SESSION)) == 2
        assert storage.get_item(SESSION).tags == ["project/kb"]

    def test_an_ask_folder_needs_the_answer_every_time(self, pipeline, storage, tmp_path):
        ProjectMap(tmp_path).record(FOLDER, ASK)
        with pytest.raises(NoProject):
            save_summary(pipeline, tmp_path, record(), at=T1)
        save_summary(pipeline, tmp_path, record(), project="none", at=T1)
        assert ProjectMap(tmp_path).lookup(FOLDER) == ASK
        assert storage.get_item(SESSION).tags == []

    def test_the_owner_can_make_a_folder_ask_every_time(self, pipeline, storage, tmp_path):
        save_summary(pipeline, tmp_path, record(), project="project/kb", always_ask=True, at=T1)
        assert ProjectMap(tmp_path).lookup(FOLDER) == ASK
        assert storage.get_item(SESSION).tags == ["project/kb"]

    @pytest.mark.parametrize("answer", ["kb", "ask", "project/Not A Slug"])
    def test_an_answer_is_a_project_or_none(self, pipeline, tmp_path, answer):
        with pytest.raises(ValueError, match="not project/<name>"):
            save_summary(pipeline, tmp_path, record(), project=answer, at=T1)
        assert ProjectMap(tmp_path).lookup(FOLDER) is None

    def test_the_same_summary_adds_nothing(self, pipeline, storage, tmp_path):
        first = save_summary(pipeline, tmp_path, record(), project="none", at=T1)
        assert save_summary(pipeline, tmp_path, record(), at=T2) == first
        assert len(storage.list_versions(SESSION)) == 1
        assert len(summary_files(tmp_path)) == 1

    async def test_the_same_summary_embeds_again_a_version_that_failed(self, storage, tmp_path):
        failing = Pipeline(storage, FailingLLM())
        assert (await failing.enrich(save_summary(failing, tmp_path, record(), project="none"))).error

        version = save_summary(failing, tmp_path, record())
        assert (version.status, version.error) == (VersionStatus.PENDING, None)

    @pytest.mark.parametrize(
        "unreadable",
        [record(decision="Two\nlines"), record(goal="Text\n\n## Goal\n\nagain")],
        ids=["list item", "goal"],
    )
    def test_a_summary_that_would_not_read_back_is_refused_before_anything_is_written(
        self, pipeline, storage, tmp_path, unreadable
    ):
        with pytest.raises(ValueError):
            save_summary(pipeline, tmp_path, unreadable, project="none", at=T1)
        assert summary_files(tmp_path) == []
        assert ProjectMap(tmp_path).lookup(FOLDER) is None
        assert storage.get_item(SESSION) is None


class TestImport:
    def client(self, pipeline, folder):
        settings = Settings(api_token="secret", session_summary_dir=folder, _env_file=None)
        return TestClient(create_app(settings, pipeline=pipeline), headers=AUTH)

    def test_a_restore_rebuilds_the_sessions_from_the_folder_and_a_second_run_changes_nothing(
        self, pipeline, storage, tmp_path
    ):
        save_summary(pipeline, tmp_path, record(), project="project/kb", at=T1)
        save_summary(pipeline, tmp_path, record(goal="Read more."), at=T2)
        (tmp_path / "broken.md").write_text("# not a Summary File\n", encoding="utf-8")
        storage.versions.clear()
        storage.items.clear()
        storage.tags.clear()

        with self.client(pipeline, tmp_path) as client:
            first = client.post("/sessions/import").json()
            second = client.post("/sessions/import").json()

        assert (first["files"], first["embedding"]) == (2, 2)
        assert (second["files"], second["embedding"]) == (2, 0)
        assert [f["file"] for f in first["failed"]] == ["broken.md"]
        assert "front matter" in first["failed"][0]["reason"]
        assert {v.status for v in storage.list_versions(SESSION)} == {VersionStatus.ENRICHED}
        item = storage.get_item(SESSION)
        assert (item.first_captured_at, item.tags) == (T1, ["project/kb"])

    def test_it_embeds_again_a_version_that_failed(self, storage, tmp_path):
        failing = Pipeline(storage, FailingLLM())
        with self.client(failing, tmp_path) as client:
            save_summary(failing, tmp_path, record(), project="none", at=T1)
            client.post("/sessions/import")
            assert storage.list_versions(SESSION)[0].status is VersionStatus.FAILED

            failing.llm = FakeLLM()
            assert client.post("/sessions/import").json()["embedding"] == 1
        assert storage.list_versions(SESSION)[0].status is VersionStatus.ENRICHED

    def test_it_needs_the_folder_and_the_token(self, pipeline, tmp_path):
        with self.client(pipeline, None) as client:
            assert client.post("/sessions/import").status_code == 409
        with self.client(pipeline, tmp_path) as client:
            assert client.post("/sessions/import", headers={"Authorization": "Bearer wrong"}).status_code == 401
