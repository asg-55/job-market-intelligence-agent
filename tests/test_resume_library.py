import asyncio
import sqlite3
from types import SimpleNamespace

import httpx
from test_scoring import profile, vacancy

from job_copilot.api import app
from job_copilot.database import Repository
from job_copilot.domain import ScoreResult
from job_copilot.profile_store import ProfileStore
from job_copilot.resume_advisor import GeneratedResumeAdvice


def test_repository_keeps_multiple_versioned_resumes(tmp_path) -> None:
    repository = Repository(tmp_path / "resumes.db")
    first = repository.create_resume(
        "AI Product Engineer", ["AI Product Engineer"], "Product resume " * 10
    )
    second = repository.create_resume(
        "Prompt Engineer", ["Prompt Engineer"], "Prompt resume " * 10
    )

    assert first["id"] != second["id"]
    assert len(repository.list_resumes()) == 2
    assert "content" not in repository.list_resumes()[0]

    changed = repository.update_resume(first["id"], content="Updated product resume " * 8)
    assert changed is not None
    assert changed["version"] == 2
    assert changed["content_sha256"] != first["content_sha256"]

    archived = repository.update_resume(first["id"], archived=True)
    assert archived is not None
    assert archived["version"] == 2
    assert [item["id"] for item in repository.list_resumes()] == [second["id"]]
    assert len(repository.list_resumes(include_archived=True)) == 2


def test_repository_migrates_existing_resume_advice_table(tmp_path) -> None:
    database_path = tmp_path / "migration.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE resume_advice (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vacancy_id TEXT NOT NULL,
                profile_version TEXT NOT NULL,
                resume_sha256 TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                result_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    repository = Repository(database_path)
    with repository.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(resume_advice)")}

    assert {"resume_id", "resume_version"} <= columns


def test_resume_api_edits_library_and_hides_archived_items(tmp_path) -> None:
    async def scenario() -> None:
        repository = Repository(tmp_path / "api.db")
        app.state.container = SimpleNamespace(repository=repository)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/resumes",
                json={
                    "name": "AI Operations",
                    "target_roles": ["AI Operations Manager"],
                    "content": "Operations resume content " * 5,
                },
            )
            changed = await client.patch(
                f"/resumes/{created.json()['id']}",
                json={"name": "AI Operations Lead"},
            )
            archived = await client.patch(
                f"/resumes/{created.json()['id']}", json={"archived": True}
            )
            visible = await client.get("/resumes")
            all_items = await client.get("/resumes?include_archived=true")

        assert created.status_code == 201
        assert changed.json()["version"] == 2
        assert archived.json()["archived"] is True
        assert visible.json() == []
        assert len(all_items.json()) == 1
        assert "content" not in all_items.json()[0]

    asyncio.run(scenario())


def test_resume_advice_uses_selected_library_version(tmp_path) -> None:
    class FakeAdvisor:
        async def generate(self, vacancy_item, candidate, resume_text, **options):
            assert vacancy_item.id == "42"
            assert candidate.verified_facts == ["Built RAG"]
            assert resume_text == "Selected private resume " * 5
            assert options == {"language": "ru"}
            return GeneratedResumeAdvice(
                fact_backed_bullets=[],
                presentation_changes=[],
                skills_to_emphasize=[],
                honest_gaps=[],
                fact_trace=[],
                model="test-model",
            )

    async def scenario() -> None:
        repository = Repository(tmp_path / "advice.db")
        repository.save_evaluation(
            vacancy(),
            ScoreResult(80, 80, 80, 80, True, ["Python"], [], [], "good"),
        )
        selected = repository.create_resume(
            "RAG Engineer", ["RAG Engineer"], "Selected private resume " * 5
        )
        store = ProfileStore(tmp_path / "profile.json")
        store.save(profile(verified_facts=["Built RAG"]))
        app.state.container = SimpleNamespace(
            repository=repository,
            profile_store=store,
            resume_advisor=FakeAdvisor(),
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/vacancies/42/resume-advice",
                json={"resume_id": selected["id"], "language": "ru"},
            )

        saved = repository.get_resume_advice(response.json()["id"])
        assert response.status_code == 200
        assert response.json()["resume_id"] == selected["id"]
        assert response.json()["resume_version"] == 1
        assert response.json()["metadata"]["source_resume_stored"] is True
        assert saved is not None
        assert saved["resume_id"] == selected["id"]
        assert saved["resume_version"] == 1

    asyncio.run(scenario())
