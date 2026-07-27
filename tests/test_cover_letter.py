import asyncio
import json
from types import SimpleNamespace

import httpx
from test_scoring import profile, vacancy

from job_copilot.api import app
from job_copilot.cover_letter import (
    FactTrace,
    GeneratedCoverLetter,
    OpenAICompatibleCoverLetterGenerator,
)
from job_copilot.database import Repository
from job_copilot.domain import ScoreResult
from job_copilot.profile_store import ProfileStore


def test_generator_keeps_fact_trace_and_audit_metadata() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert payload["response_format"]["type"] == "json_schema"
            user_payload = json.loads(payload["messages"][1]["content"])
            assert user_payload["candidate"]["verified_facts"][0]["index"] == 0
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "body": [
                                            {
                                                "text": "Я создал локальный RAG-ассистент.",
                                                "fact_indexes": [0],
                                            }
                                        ],
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ],
                    "usage": {"total_tokens": 123},
                },
            )

        client = httpx.AsyncClient(
            base_url="http://ollama.test/v1/", transport=httpx.MockTransport(handler)
        )
        generator = OpenAICompatibleCoverLetterGenerator(
            "http://ollama.test/v1", "ollama", "qwen3.5:9b", client=client
        )
        candidate = profile(verified_facts=["Создал локальный RAG-ассистент"])
        result = await generator.generate(vacancy(), candidate)

        assert "RAG-ассистент" in result.text
        assert result.fact_trace[0].facts == candidate.verified_facts
        assert result.model == "qwen3.5:9b"
        assert result.prompt_version == "cover-letter-v1"
        assert result.usage == {"total_tokens": 123}
        await client.aclose()

    asyncio.run(scenario())


def test_generator_rejects_unknown_fact_reference() -> None:
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
                                        "body": [
                                            {
                                                "text": "Unsupported claim",
                                                "fact_indexes": [4],
                                            }
                                        ],
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
        generator = OpenAICompatibleCoverLetterGenerator(
            "http://ollama.test/v1", "ollama", "qwen3.5:9b", client=client
        )
        try:
            await generator.generate(vacancy(), profile(verified_facts=["One fact"]))
        except ValueError as error:
            assert "unknown verified fact" in str(error)
        else:
            raise AssertionError("Unknown fact indexes must be rejected")
        await client.aclose()

    asyncio.run(scenario())


def test_api_saves_cover_letter_as_draft(tmp_path) -> None:
    class FakeGenerator:
        async def generate(self, vacancy_item, candidate, **options):
            assert vacancy_item.id == "42"
            assert candidate.verified_facts == ["Built a RAG assistant"]
            assert options == {"language": "en", "tone": "concise"}
            return GeneratedCoverLetter(
                text="A concise draft",
                fact_trace=[
                    FactTrace(
                        paragraph="A concise draft", facts=["Built a RAG assistant"]
                    )
                ],
                model="test-model",
            )

    async def scenario() -> None:
        repository = Repository(tmp_path / "cover-letter.db")
        repository.save_evaluation(
            vacancy(),
            ScoreResult(80, 80, 80, 80, True, ["Python"], [], [], "good"),
        )
        store = ProfileStore(tmp_path / "profile.json")
        store.save(profile(verified_facts=["Built a RAG assistant"]))
        app.state.container = SimpleNamespace(
            repository=repository,
            profile_store=store,
            cover_letter_generator=FakeGenerator(),
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/vacancies/42/cover-letter",
                json={"language": "en", "tone": "concise"},
            )
            loaded = await client.get(f"/cover-letters/{created.json()['id']}")

        assert created.status_code == 200
        assert created.json()["status"] == "draft"
        assert loaded.status_code == 200
        assert loaded.json()["text"] == "A concise draft"
        assert loaded.json()["metadata"]["prompt_version"] == "cover-letter-v1"

    asyncio.run(scenario())
