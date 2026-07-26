from job_copilot.config import CandidateProfile
from job_copilot.domain import Vacancy
from job_copilot.scoring import ExplainableScorer


def vacancy(**overrides) -> Vacancy:
    values = {
        "id": "42",
        "name": "LLM Engineer",
        "employer": "Example",
        "area_id": "1",
        "area_name": "Москва",
        "experience_id": "between1And3",
        "experience_name": "1–3 года",
        "employment_name": "Полная занятость",
        "schedule_id": "remote",
        "schedule_name": "Удалённая работа",
        "salary_from": 180000,
        "salary_to": None,
        "salary_currency": "RUR",
        "salary_gross": False,
        "description": "Build Python RAG services with FastAPI and Docker",
        "key_skills": ["Python", "RAG"],
        "url": "https://hh.ru/vacancy/42",
        "published_at": None,
    }
    values.update(overrides)
    return Vacancy(**values)


def profile(**overrides) -> CandidateProfile:
    values = {
        "target_roles": ["LLM Engineer"],
        "skills": ["Python", "RAG", "REST API", "Docker"],
        "skill_aliases": {"REST API": ["FastAPI"]},
        "accepted_experience_ids": ["between1And3"],
        "remote_only": True,
    }
    values.update(overrides)
    return CandidateProfile(**values)


def test_matching_vacancy_gets_explainable_high_score() -> None:
    result = ExplainableScorer().score(vacancy(), profile())
    assert result.passed_hard_filters
    assert result.total_score >= 80
    assert result.matched_skills == ["Python", "RAG", "REST API", "Docker"]
    assert "совпадения" in result.explanation


def test_hard_filter_caps_score() -> None:
    result = ExplainableScorer().score(
        vacancy(schedule_id="fullDay", schedule_name="Полный день"), profile()
    )
    assert not result.passed_hard_filters
    assert result.total_score <= 39
    assert "Требуется удалённый формат" in result.rejection_reasons


def test_excluded_direction_is_rejected() -> None:
    result = ExplainableScorer().score(
        vacancy(description="Python data scientist"), profile(excluded_terms=["data scientist"])
    )
    assert not result.passed_hard_filters
