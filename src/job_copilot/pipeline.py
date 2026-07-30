from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from .config import CandidateProfile, SearchProfile, SearchQuery
from .database import Repository
from .domain import Vacancy
from .hh import HHClient
from .llm import OpenAICompatibleEvaluator
from .scoring import ExplainableScorer
from .telegram import TelegramNotifier


@dataclass(slots=True)
class RunSummary:
    found: int = 0
    new: int = 0
    known: int = 0
    reevaluated: int = 0
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
        profile_version = profile.fingerprint()
        for search_profile, search in profile.active_searches():
            async for vacancy in self._search_safely(search, pages, summary):
                if vacancy.id in seen_in_run:
                    self._record_search_match(vacancy.id, profile_version, search_profile)
                    continue
                seen_in_run.add(vacancy.id)
                summary.found += 1
                was_known = self.repository.has_vacancy(vacancy.id)
                if self.repository.has_evaluation(vacancy.id, profile_version):
                    self._record_search_match(vacancy.id, profile_version, search_profile)
                    summary.known += 1
                    continue
                if was_known:
                    summary.reevaluated += 1
                else:
                    summary.new += 1
                result = self.scorer.score(vacancy, profile)
                if result.passed_hard_filters and self.llm_evaluator is not None:
                    try:
                        result = await self.llm_evaluator.enrich(vacancy, profile, result)
                    except (httpx.HTTPError, KeyError, TypeError, ValueError):
                        summary.errors += 1
                self.repository.save_evaluation(vacancy, result, profile_version)
                self._record_search_match(vacancy.id, profile_version, search_profile)
                if result.passed_hard_filters:
                    summary.passed += 1
                if (
                    result.passed_hard_filters
                    and result.total_score >= self.notification_threshold
                    and self.notifier is not None
                ):
                    try:
                        await self.notifier.send_vacancy(vacancy, result, search_profile)
                        summary.notified += 1
                    except Exception:
                        summary.errors += 1
        return summary

    async def _search_safely(
        self,
        search: SearchQuery,
        pages: int,
        summary: RunSummary,
    ) -> AsyncIterator[Vacancy]:
        try:
            async for vacancy in self.hh.search(search, pages=pages):
                yield vacancy
        except httpx.HTTPError:
            summary.errors += 1

    def _record_search_match(
        self,
        vacancy_id: str,
        profile_version: str,
        search_profile: SearchProfile | None,
    ) -> None:
        if search_profile is None:
            return
        self.repository.add_search_match(
            vacancy_id,
            profile_version,
            search_profile.key,
            search_profile.name,
            search_profile.resume_id,
        )
