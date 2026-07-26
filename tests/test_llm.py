import asyncio
import json

import httpx

from job_copilot.llm import OpenAICompatibleEvaluator
from test_scoring import profile, vacancy


def test_structured_evaluator_blends_score_and_keeps_audit_metadata() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert request.url.path == "/v1/chat/completions"
            assert payload["response_format"]["type"] == "json_schema"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "match_score": 90,
                                        "recommended_action": "apply",
                                        "matching_strengths": ["Python", "RAG"],
                                        "missing_requirements": [],
                                        "critical_gaps": [],
                                        "resume_changes": ["Поднять RAG-проект выше"],
                                        "confidence": 0.87,
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
        evaluator = OpenAICompatibleEvaluator(
            "http://ollama.test/v1", "ollama", "qwen3.5:9b", client=client
        )
        from job_copilot.scoring import ExplainableScorer

        baseline = ExplainableScorer().score(vacancy(), profile())
        result = await evaluator.enrich(vacancy(), profile(), baseline)

        assert result.total_score == round(baseline.total_score * 0.4 + 90 * 0.6)
        assert result.llm_analysis is not None
        assert result.llm_analysis["model"] == "qwen3.5:9b"
        assert result.llm_analysis["prompt_version"] == "vacancy-evaluator-v1"
        assert "LLM: Python, RAG" in result.explanation
        await client.aclose()

    asyncio.run(scenario())


def test_hard_filter_failure_never_calls_llm() -> None:
    async def scenario() -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            raise AssertionError("LLM must not be called after a hard-filter failure")

        client = httpx.AsyncClient(
            base_url="http://ollama.test/v1/", transport=httpx.MockTransport(handler)
        )
        evaluator = OpenAICompatibleEvaluator(
            "http://ollama.test/v1", "ollama", "qwen3.5:9b", client=client
        )
        from job_copilot.scoring import ExplainableScorer

        rejected_profile = profile(remote_only=True)
        onsite = vacancy(schedule_id="fullDay")
        baseline = ExplainableScorer().score(onsite, rejected_profile)
        result = await evaluator.enrich(onsite, rejected_profile, baseline)

        assert result is baseline
        await client.aclose()

    asyncio.run(scenario())
