from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Protocol

import httpx

from .config import CandidateProfile, SearchProfile, SearchQuery
from .database import Repository
from .domain import Vacancy
from .hh import HHAPIError, HHClient
from .llm import OpenAICompatibleEvaluator
from .scoring import ExplainableScorer
from .sources import SourceAPIError
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
    source_status: str = "ok"
    source_message: str | None = None
    sources: dict[str, dict[str, str | int | None]] = field(default_factory=dict)


class VacancySource(Protocol):
    source_name: str

    def search(self, query: SearchQuery, pages: int = 1) -> AsyncIterator[Vacancy]: ...


class MonitoringPipeline:
    def __init__(
        self,
        hh: HHClient,
        repository: Repository,
        scorer: ExplainableScorer,
        llm_evaluator: OpenAICompatibleEvaluator | None = None,
        notifier: TelegramNotifier | None = None,
        notification_threshold: int = 65,
        additional_sources: list[VacancySource] | None = None,
    ) -> None:
        self.hh = hh
        self.sources: list[VacancySource] = [hh, *(additional_sources or [])]
        self.repository = repository
        self.scorer = scorer
        self.llm_evaluator = llm_evaluator
        self.notifier = notifier
        self.notification_threshold = notification_threshold

    async def run(
        self, profile: CandidateProfile, pages: int = 1, trigger: str = "manual"
    ) -> RunSummary:
        summary = RunSummary()
        seen_in_run: set[str] = set()
        profile_version = profile.fingerprint()
        for source in self.sources:
            source_name = getattr(source, "source_name", "hh")
            summary.sources[source_name] = {"status": "ok", "message": None, "errors": 0}
            for search_profile, search in profile.active_searches():
                async for vacancy in self._search_safely(
                    source, source_name, search, pages, summary
                ):
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
                if summary.sources[source_name]["status"] != "ok":
                    break
        self._summarize_sources(summary)
        self.repository.save_monitor_run(trigger, profile_version, asdict(summary))
        return summary

    async def _search_safely(
        self,
        source: VacancySource,
        source_name: str,
        search: SearchQuery,
        pages: int,
        summary: RunSummary,
    ) -> AsyncIterator[Vacancy]:
        try:
            async for vacancy in source.search(search, pages=pages):
                yield vacancy
        except HHAPIError as error:
            self._record_source_error(summary, source_name, error.category, error.user_message)
        except SourceAPIError as error:
            self._record_source_error(summary, source_name, error.category, error.user_message)
        except httpx.HTTPError:
            self._record_source_error(
                summary,
                source_name,
                "unavailable",
                f"Источник {source_name} временно недоступен. Повторим попытку по расписанию.",
            )

    @staticmethod
    def _record_source_error(
        summary: RunSummary, source_name: str, status: str, message: str
    ) -> None:
        summary.errors += 1
        summary.sources[source_name] = {"status": status, "message": message, "errors": 1}

    @staticmethod
    def _summarize_sources(summary: RunSummary) -> None:
        failed = [item for item in summary.sources.values() if item["status"] != "ok"]
        if not failed:
            return
        if len(summary.sources) == 1:
            summary.source_status = str(failed[0]["status"])
            summary.source_message = str(failed[0]["message"])
            return
        if len(failed) < len(summary.sources):
            summary.source_status = "partial"
        else:
            statuses = {str(item["status"]) for item in failed}
            summary.source_status = statuses.pop() if len(statuses) == 1 else "unavailable"
        summary.source_message = " ".join(
            str(item["message"]) for item in failed if item["message"]
        )

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
