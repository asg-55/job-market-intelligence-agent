from __future__ import annotations

from dataclasses import dataclass

from .config import CandidateProfile, Settings
from .database import Repository
from .hh import HHClient
from .pipeline import MonitoringPipeline
from .scoring import ExplainableScorer
from .telegram import TelegramNotifier


@dataclass
class AppContainer:
    settings: Settings
    profile: CandidateProfile
    repository: Repository
    hh: HHClient
    notifier: TelegramNotifier | None
    pipeline: MonitoringPipeline

    async def close(self) -> None:
        await self.hh.close()
        if self.notifier:
            await self.notifier.close()


def build_container(settings: Settings) -> AppContainer:
    profile = CandidateProfile.from_file(settings.profile_path)
    repository = Repository(settings.database_path)
    hh = HHClient(settings.hh_base_url, settings.hh_user_agent, settings.hh_access_token)
    notifier = None
    if settings.telegram_bot_token and settings.telegram_chat_id:
        notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    pipeline = MonitoringPipeline(
        hh,
        repository,
        ExplainableScorer(),
        notifier,
        settings.min_notification_score,
    )
    return AppContainer(settings, profile, repository, hh, notifier, pipeline)
