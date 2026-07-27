import asyncio
import json
from types import SimpleNamespace

import httpx
from job_copilot.resume_advisor import (
    FactBackedBullet,
    GeneratedResumeAdvice,
    OpenAICompatibleResumeAdvisor,
    ResumeFactTrace,
)
from test_scoring import profile, vacancy

from job_copilot.api import app
from job_copilot.database import Repository
from job_copilot.domain import ScoreResult
from job_copilot.profile_store import ProfileStore


def test_advisor_returns_fact_traces_and_profile_skills() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            user_payload = json.loads(payload["messages"][1]["content"])
            assert user_payload["source_resume"].startswith("Current resume")
            assert user_payload["candidate"]["verified_facts"][0]["index"] == 0
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "fact_backed_bullets": [
                                            {
                                                "section": "projects",
                                                "text": "Built a local RAG assistant",
                                                "fact_indexes": [0],
                                                "vacancy_requirements": ["RAG"],
                                            }
                                        ],
                                        "presentation_changes": [],
                                        "skills_to_emphasize": ["Python", "RAG"],
                                        "honest_gaps": ["No verified Kubernetes experience"],
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {"total_tokens": 321},
                },
            )

        client = httpx.AsyncClient(
            base_url="http://ollama.test/v1/", transport=httpx.MockTransport(handler)
        )
        advisor = OpenAICompatibleResumeAdvisor(
            "http://ollama.test/v1", "ollama", "qwen3.5:9b", client=client
        )
        candidate = profile(verified_facts=["Built a local RAG assistant"])
        result = await advisor.generate(vacancy(), candidate, "Current resume text" * 5)

        assert result.skills_to_emphasize == ["Python", "RAG"]
        assert result.fact_trace[0].facts == candidate.verified_facts
        assert result.prompt_version == "resume-advisor-v1"
        assert result.usage == {"total_tokens": 321}
        await client.aclose()

    asyncio.run(scenario())


def test_advisor_rejects_skill_absent_from_profile() -> None:
    async def scenario() -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "fact_backed_bullets": [],
                                        "presentation_changes": [],
                                        "skills_to_emphasize": ["Kubernetes"],
                                        "honest_gaps": [],
                                    }
                                )
                            }
                        }
                    ]
                },
            )

        client = httpx.AsyncClient(
            base_url="http://ollama.test/v1/", transport=httpx.MockTransport(handler)
        )
        advisor = OpenAICompatibleResumeAdvisor(
            "http://ollama.test/v1", "ollama", "qwen3.5:9b", client=client
        )
        try:
            await advisor.generate(
                vacancy(), profile(verified_facts=["Built RAG"]), "Resume text" * 10
            )
        except ValueError as error:
            assert "absent from the profile" in str(error)
        else:
            raise AssertionError("Unknown skills must be rejected")
        await client.aclose()

    asyncio.run(scenario())


def test_api_persists_advice_but_not_source_resume(tmp_path) -> None:
    class FakeAdvisor:
        async def generate(self, vacancy_item, candidate, resume_text, **options):
            assert vacancy_item.id == "42"
            assert candidate.verified_facts == ["Built RAG"]
            assert resume_text.startswith("Private resume")
            assert options == {"language": "en"}
            bullet = FactBackedBullet(
                section="projects",
                text="Built RAG",
                fact_indexes=[0],
                vacancy_requirements=["RAG"],
            )
            return GeneratedResumeAdvice(
                fact_backed_bullets=[bullet],
                presentation_changes=[],
                skills_to_emphasize=["RAG"],
                honest_gaps=[],
                fact_trace=[
                    ResumeFactTrace(
                        bullet="Built RAG",
                        facts=["Built RAG"],
                        vacancy_requirements=["RAG"],
                    )
                ],
                model="test-model",
            )

    async def scenario() -> None:
        repository = Repository(tmp_path / "resume-advice.db")
        repository.save_evaluation(
            vacancy(),
            ScoreResult(80, 80, 80, 80, True, ["Python"], [], [], "good"),
        )
        store = ProfileStore(tmp_path / "profile.json")
        store.save(profile(verified_facts=["Built RAG"]))
        app.state.container = SimpleNamespace(
            repository=repository,
            profile_store=store,
            resume_advisor=FakeAdvisor(),
        )
        source_resume = "Private resume with personal details " * 4

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/vacancies/42/resume-advice",
                json={"resume_text": source_resume, "language": "en"},
            )
            loaded = await client.get(f"/resume-advice/{created.json()['id']}")

        assert created.status_code == 200
        assert created.json()["status"] == "draft"
        assert created.json()["metadata"]["source_resume_stored"] is False
        assert loaded.status_code == 200
        assert loaded.json()["result"]["skills_to_emphasize"] == ["RAG"]
        assert source_resume not in json.dumps(repository.get_resume_advice(1))

    asyncio.run(scenario())
