from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .cover_letter import OpenAICompatibleCoverLetterGenerator
from .database import Repository
from .hh import HHClient
from .llm import OpenAICompatibleEvaluator
from .pipeline import MonitoringPipeline
from .profile_store import ProfileStore
from .remotive import RemotiveClient
from .resume_advisor import OpenAICompatibleResumeAdvisor
from .scoring import ExplainableScorer
from .telegram import TelegramNotifier
from .telegram_bot import TelegramBotController


@dataclass
class AppContainer:
    settings: Settings
    profile_store: ProfileStore
    repository: Repository
    hh: HHClient
    remotive: RemotiveClient | None
    notifier: TelegramNotifier | None
    telegram_bot: TelegramBotController | None
    llm_evaluator: OpenAICompatibleEvaluator | None
    cover_letter_generator: OpenAICompatibleCoverLetterGenerator | None
    resume_advisor: OpenAICompatibleResumeAdvisor | None
    pipeline: MonitoringPipeline

    async def close(self) -> None:
        await self.hh.close()
        if self.remotive:
            await self.remotive.close()
        if self.notifier:
            await self.notifier.close()
        if self.llm_evaluator:
            await self.llm_evaluator.close()
        if self.cover_letter_generator:
            await self.cover_letter_generator.close()
        if self.resume_advisor:
            await self.resume_advisor.close()


def build_container(settings: Settings) -> AppContainer:
    profile_store = ProfileStore(settings.profile_path, "config/profile.example.json")
    repository = Repository(settings.database_path)
    hh = HHClient(settings.hh_base_url, settings.hh_user_agent, settings.hh_access_token)
    remotive = None
    if settings.remotive_enabled:
        remotive = RemotiveClient(
            settings.remotive_base_url,
            cache_hours=settings.remotive_cache_hours,
        )
    notifier = None
    telegram_bot = None
    if settings.telegram_bot_token and settings.telegram_chat_id:
        notifier = TelegramNotifier(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            feedback_enabled=bool(settings.telegram_webhook_secret),
        )
        telegram_bot = TelegramBotController(
            repository,
            profile_store,
            notifier,
            public_app_url=settings.public_app_url,
        )
    llm_evaluator = None
    cover_letter_generator = None
    resume_advisor = None
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
        resume_advisor = OpenAICompatibleResumeAdvisor(
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
        additional_sources=[remotive] if remotive else None,
    )
    return AppContainer(
        settings=settings,
        profile_store=profile_store,
        repository=repository,
        hh=hh,
        remotive=remotive,
        notifier=notifier,
        telegram_bot=telegram_bot,
        llm_evaluator=llm_evaluator,
        cover_letter_generator=cover_letter_generator,
        resume_advisor=resume_advisor,
        pipeline=pipeline,
    )
