from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .cover_letter import OpenAICompatibleCoverLetterGenerator
from .database import Repository
from .hh import HHClient
from .llm import OpenAICompatibleEvaluator
from .pipeline import MonitoringPipeline
from .profile_store import ProfileStore
from .scoring import ExplainableScorer
from .telegram import TelegramNotifier


@dataclass
class AppContainer:
    settings: Settings
    profile_store: ProfileStore
    repository: Repository
    hh: HHClient
    notifier: TelegramNotifier | None
    llm_evaluator: OpenAICompatibleEvaluator | None
    cover_letter_generator: OpenAICompatibleCoverLetterGenerator | None
    pipeline: MonitoringPipeline

    async def close(self) -> None:
        await self.hh.close()
        if self.notifier:
            await self.notifier.close()
        if self.llm_evaluator:
            await self.llm_evaluator.close()
        if self.cover_letter_generator:
            await self.cover_letter_generator.close()


def build_container(settings: Settings) -> AppContainer:
    profile_store = ProfileStore(settings.profile_path, "config/profile.example.json")
    repository = Repository(settings.database_path)
    hh = HHClient(settings.hh_base_url, settings.hh_user_agent, settings.hh_access_token)
    notifier = None
    if settings.telegram_bot_token and settings.telegram_chat_id:
        notifier = TelegramNotifier(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            feedback_enabled=bool(settings.telegram_webhook_secret),
        )
    llm_evaluator = None
    cover_letter_generator = None
    if settings.llm_model:
        llm_evaluator = OpenAICompatibleEvaluator(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
            llm_weight=settings.llm_weight,
            timeout=settings.llm_timeout,
        )
        cover_letter_generator = OpenAICompatibleCoverLetterGenerator(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
            timeout=settings.llm_timeout,
        )
    pipeline = MonitoringPipeline(
        hh,
        repository,
        ExplainableScorer(),
        llm_evaluator,
        notifier,
        settings.min_notification_score,
    )
    return AppContainer(
        settings=settings,
        profile_store=profile_store,
        repository=repository,
        hh=hh,
        notifier=notifier,
        llm_evaluator=llm_evaluator,
        cover_letter_generator=cover_letter_generator,
        pipeline=pipeline,
    )
