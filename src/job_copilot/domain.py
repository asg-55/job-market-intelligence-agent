from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Vacancy:
    id: str
    name: str
    employer: str
    area_id: str | None
    area_name: str | None
    experience_id: str | None
    experience_name: str | None
    employment_name: str | None
    schedule_id: str | None
    schedule_name: str | None
    salary_from: int | None
    salary_to: int | None
    salary_currency: str | None
    salary_gross: bool | None
    description: str
    key_skills: list[str]
    url: str
    published_at: str | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def searchable_text(self) -> str:
        return " ".join([self.name, self.description, *self.key_skills]).lower()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(slots=True)
class ScoreResult:
    total_score: int
    hard_skills_score: int
    role_score: int
    conditions_score: int
    passed_hard_filters: bool
    matched_skills: list[str]
    missing_skills: list[str]
    rejection_reasons: list[str]
    explanation: str
    llm_analysis: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
