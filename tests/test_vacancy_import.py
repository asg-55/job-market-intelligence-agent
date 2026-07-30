import asyncio
from types import SimpleNamespace

import httpx

from job_copilot.api import app
from job_copilot.config import CandidateProfile
from job_copilot.database import Repository
from job_copilot.scoring import ExplainableScorer


class ProfileStoreStub:
    def load(self) -> CandidateProfile:
        return CandidateProfile(
            target_roles=["AI Engineer"],
            skills=["Python", "RAG"],
            remote_only=True,
        )


def test_manual_linkedin_import_is_scored_and_deduplicated(tmp_path) -> None:
    async def scenario() -> None:
        repository = Repository(tmp_path / "manual.db")
        app.state.container = SimpleNamespace(
            repository=repository,
            profile_store=ProfileStoreStub(),
            pipeline=SimpleNamespace(scorer=ExplainableScorer()),
        )
        payload = {
            "source": "linkedin",
            "name": "AI Engineer",
            "employer": "Example Labs",
            "url": "https://www.linkedin.com/jobs/view/123",
            "description": "Build remote Python and RAG services with a product team.",
            "remote": True,
            "key_skills": ["Python", "RAG"],
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post("/vacancies/import", json=payload)
            second = await client.post("/vacancies/import", json=payload)

        assert first.status_code == 201
        assert first.json()["created"] is True
        assert first.json()["vacancy"]["source"] == "linkedin"
        assert first.json()["result"]["total_score"] >= 80
        assert second.json()["created"] is False
        assert len(repository.list_vacancies()) == 1

    asyncio.run(scenario())
