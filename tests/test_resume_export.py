import asyncio
from io import BytesIO
from types import SimpleNamespace

import httpx
from docx import Document
from test_scoring import vacancy

from job_copilot.api import app
from job_copilot.database import Repository
from job_copilot.domain import ScoreResult
from job_copilot.resume_export import build_resume_docx


def test_docx_export_contains_editable_resume_content() -> None:
    payload = build_resume_docx(
        {
            "name": "AI Product Engineer",
            "target_roles": ["AI Engineer", "Product Engineer"],
            "content": "ОПЫТ\n- Создал локальный RAG-ассистент\nPython, Docker, FastAPI",
        }
    )

    document = Document(BytesIO(payload))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)

    assert payload.startswith(b"PK")
    assert document.sections[0].top_margin.inches == 1
    assert "AI Product Engineer" in text
    assert "Создал локальный RAG-ассистент" in text


def test_api_creates_linked_copy_and_exports_docx(tmp_path) -> None:
    async def scenario() -> None:
        repository = Repository(tmp_path / "resume-export.db")
        repository.save_evaluation(
            vacancy(),
            ScoreResult(80, 80, 80, 80, True, ["Python"], [], [], "good"),
        )
        source = repository.create_resume(
            "AI Engineer",
            ["AI Engineer"],
            "ОПЫТ\n- Создал RAG-ассистент на Python и FastAPI " * 3,
        )
        advice_id = repository.save_resume_advice(
            "42",
            "profile-v1",
            source["content_sha256"],
            {"skills_to_emphasize": ["Python"]},
            {"model": "test"},
            resume_id=source["id"],
            resume_version=source["version"],
        )
        app.state.container = SimpleNamespace(repository=repository)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/vacancies/42/adapted-resume",
                json={"resume_id": source["id"], "advice_id": advice_id},
            )
            exported = await client.get(
                f"/resumes/{created.json()['id']}/export.docx"
            )

        assert created.status_code == 201
        assert created.json()["source_resume_id"] == source["id"]
        assert created.json()["source_resume_version"] == source["version"]
        assert created.json()["vacancy_id"] == "42"
        assert created.json()["advice_id"] == advice_id
        assert exported.status_code == 200
        assert exported.content.startswith(b"PK")
        assert exported.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument"
        )

    asyncio.run(scenario())


def test_adapted_copy_rejects_advice_for_old_resume_version(tmp_path) -> None:
    async def scenario() -> None:
        repository = Repository(tmp_path / "stale-advice.db")
        repository.save_evaluation(
            vacancy(),
            ScoreResult(80, 80, 80, 80, True, ["Python"], [], [], "good"),
        )
        source = repository.create_resume(
            "AI Engineer",
            ["AI Engineer"],
            "Original verified resume content " * 4,
        )
        advice_id = repository.save_resume_advice(
            "42",
            "profile-v1",
            source["content_sha256"],
            {},
            {},
            resume_id=source["id"],
            resume_version=source["version"],
        )
        repository.update_resume(source["id"], content="Updated resume content " * 5)
        app.state.container = SimpleNamespace(repository=repository)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/vacancies/42/adapted-resume",
                json={"resume_id": source["id"], "advice_id": advice_id},
            )

        assert response.status_code == 409
        assert response.json()["detail"] == "Source resume changed after advice"

    asyncio.run(scenario())
