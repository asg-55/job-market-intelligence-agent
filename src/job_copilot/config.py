from __future__ import annotations

import json
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    area: str | None = None
    period: int = Field(default=3, ge=1, le=30)


class SearchProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,49}$")
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    resume_id: int | None = Field(default=None, ge=1)
    searches: list[SearchQuery] = Field(min_length=1, max_length=20)


class CandidateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "Candidate"
    target_roles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    skill_aliases: dict[str, list[str]] = Field(default_factory=dict)
    required_terms: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    allowed_area_ids: list[str] = Field(default_factory=list)
    remote_only: bool = False
    accepted_experience_ids: list[str] = Field(default_factory=list)
    minimum_salary: int | None = None
    salary_currency: str = "RUR"
    verified_facts: list[str] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)
    preferences: str = Field(default="", max_length=5000)
    searches: list[SearchQuery] = Field(default_factory=list)
    search_profiles: list[SearchProfile] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_search_profile_keys(self) -> CandidateProfile:
        keys = [item.key for item in self.search_profiles]
        if len(keys) != len(set(keys)):
            raise ValueError("Search profile keys must be unique")
        return self

    def active_searches(self) -> list[tuple[SearchProfile | None, SearchQuery]]:
        if self.search_profiles:
            return [
                (search_profile, search)
                for search_profile in self.search_profiles
                if search_profile.enabled
                for search in search_profile.searches
            ]
        return [(None, search) for search in self.searches]

    @classmethod
    def from_file(cls, path: str | Path) -> CandidateProfile:
        with Path(path).open(encoding="utf-8") as file:
            return cls.model_validate(json.load(file))

    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()[:16]}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    hh_base_url: str = "https://api.hh.ru"
    hh_user_agent: str = "JobMarketIntelligenceAgent/0.1 (configure-email@example.com)"
    hh_access_token: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_webhook_secret: str | None = None
    public_app_url: str | None = None
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str | None = None
    llm_weight: float = Field(default=0.6, ge=0, le=1)
    llm_timeout: float = Field(default=90, ge=5, le=600)
    database_path: Path = Path("data/job_copilot.db")
    profile_path: Path = Path("config/profile.json")
    min_notification_score: int = Field(default=65, ge=0, le=100)


@lru_cache
def get_settings() -> Settings:
    return Settings()
