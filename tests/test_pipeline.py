import asyncio

import httpx

from job_copilot.config import SearchQuery
from job_copilot.database import Repository
from job_copilot.pipeline import MonitoringPipeline
from job_copilot.scoring import ExplainableScorer
from test_scoring import profile, vacancy


class FakeHHClient:
    async def search(self, query: SearchQuery, pages: int = 1):
        del query, pages
        yield vacancy()


class FailingLLMEvaluator:
    def __init__(self) -> None:
        self.calls = 0

    async def enrich(self, vacancy_item, candidate_profile, baseline):
        del vacancy_item, candidate_profile, baseline
        self.calls += 1
        raise httpx.ConnectError("LLM unavailable")


def test_llm_failure_falls_back_to_baseline_and_monitoring_continues(tmp_path) -> None:
    async def scenario() -> None:
        repository = Repository(tmp_path / "fallback.db")
        llm = FailingLLMEvaluator()
        pipeline = MonitoringPipeline(
            FakeHHClient(), repository, ExplainableScorer(), llm_evaluator=llm
        )
        candidate = profile(searches=[{"text": "LLM engineer"}])

        summary = await pipeline.run(candidate)

        assert summary.new == 1
        assert summary.errors == 1
        assert llm.calls == 1
        assert repository.list_vacancies()[0]["result"]["llm_analysis"] is None

    asyncio.run(scenario())


def test_known_vacancy_is_not_sent_to_llm_again(tmp_path) -> None:
    async def scenario() -> None:
        repository = Repository(tmp_path / "known.db")
        candidate = profile(searches=[{"text": "LLM engineer"}])
        item = vacancy()
        baseline = ExplainableScorer().score(item, candidate)
        repository.save_evaluation(item, baseline, candidate.fingerprint())
        llm = FailingLLMEvaluator()
        pipeline = MonitoringPipeline(
            FakeHHClient(), repository, ExplainableScorer(), llm_evaluator=llm
        )

        summary = await pipeline.run(candidate)

        assert summary.found == 1
        assert summary.known == 1
        assert summary.new == 0
        assert llm.calls == 0

    asyncio.run(scenario())


def test_profile_change_reevaluates_known_vacancy(tmp_path) -> None:
    async def scenario() -> None:
        repository = Repository(tmp_path / "changed-profile.db")
        original = profile(searches=[{"text": "LLM engineer"}])
        changed = original.model_copy(update={"skills": [*original.skills, "PostgreSQL"]})
        item = vacancy()
        baseline = ExplainableScorer().score(item, original)
        repository.save_evaluation(item, baseline, original.fingerprint())
        llm = FailingLLMEvaluator()
        pipeline = MonitoringPipeline(
            FakeHHClient(), repository, ExplainableScorer(), llm_evaluator=llm
        )

        summary = await pipeline.run(changed)

        assert summary.reevaluated == 1
        assert summary.known == 0
        assert llm.calls == 1

    asyncio.run(scenario())
