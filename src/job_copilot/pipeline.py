from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import CandidateProfile
from .database import Repository
from .hh import HHClient
from .llm import OpenAICompatibleEvaluator
from .scoring import ExplainableScorer
from .telegram import TelegramNotifier


@dataclass(slots=True)
class RunSummary:
    found: int = 0
    new: int = 0
    known: int = 0
    passed: int = 0
    notified: int = 0
    errors: int = 0


class MonitoringPipeline:
    def __init__(
        self,
        hh: HHClient,
        repository: Repository,
        scorer: ExplainableScorer,
        llm_evaluator: OpenAICompatibleEvaluator | None = None,
        notifier: TelegramNotifier | None = None,
        notification_threshold: int = 65,
    ) -> None:
        self.hh = hh
        self.repository = repository
        self.scorer = scorer
        self.llm_evaluator = llm_evaluator
        self.notifier = notifier
        self.notification_threshold = notification_threshold

    async def run(self, profile: CandidateProfile, pages: int = 1) -> RunSummary:
        summary = RunSummary()
        seen_in_run: set[str] = set()
        for search in profile.searches:
            async for vacancy in self.hh.search(search, pages=pages):
                if vacancy.id in seen_in_run:
                    continue
                seen_in_run.add(vacancy.id)
                summary.found += 1
                was_known = self.repository.has_vacancy(vacancy.id)
                if was_known:
                    summary.known += 1
                    continue
                summary.new += 1
                result = self.scorer.score(vacancy, profile)
                if result.passed_hard_filters and self.llm_evaluator is not None:
                    try:
                        result = await self.llm_evaluator.enrich(vacancy, profile, result)
                    except (httpx.HTTPError, KeyError, TypeError, ValueError):
                        summary.errors += 1
                self.repository.save_evaluation(vacancy, result)
                if result.passed_hard_filters:
                    summary.passed += 1
                if (
                    result.passed_hard_filters
                    and result.total_score >= self.notification_threshold
                    and self.notifier is not None
                ):
                    try:
                        await self.notifier.send_vacancy(vacancy, result)
                        summary.notified += 1
                    except Exception:
                        summary.errors += 1
        return summary
