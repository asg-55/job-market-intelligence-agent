from __future__ import annotations

from dataclasses import dataclass

from .config import CandidateProfile
from .database import Repository
from .hh import HHClient
from .scoring import ExplainableScorer
from .telegram import TelegramNotifier


@dataclass(slots=True)
class RunSummary:
    found: int = 0
    new: int = 0
    passed: int = 0
    notified: int = 0
    errors: int = 0


class MonitoringPipeline:
    def __init__(
        self,
        hh: HHClient,
        repository: Repository,
        scorer: ExplainableScorer,
        notifier: TelegramNotifier | None = None,
        notification_threshold: int = 65,
    ) -> None:
        self.hh = hh
        self.repository = repository
        self.scorer = scorer
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
                result = self.scorer.score(vacancy, profile)
                self.repository.save_evaluation(vacancy, result)
                if not was_known:
                    summary.new += 1
                if result.passed_hard_filters:
                    summary.passed += 1
                if (
                    not was_known
                    and result.passed_hard_filters
                    and result.total_score >= self.notification_threshold
                    and self.notifier is not None
                ):
                    try:
                        await self.notifier.send_vacancy(vacancy, result)
                        summary.notified += 1
                    except Exception:
                        summary.errors += 1
        return summary
