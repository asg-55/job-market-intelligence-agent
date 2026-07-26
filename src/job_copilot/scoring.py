from __future__ import annotations

from .config import CandidateProfile
from .domain import ScoreResult, Vacancy


class ExplainableScorer:
    """Deterministic first-pass scoring that is cheap, auditable and testable."""

    def score(self, vacancy: Vacancy, profile: CandidateProfile) -> ScoreResult:
        text = vacancy.searchable_text()
        rejection_reasons = self._hard_filter_reasons(vacancy, profile, text)

        matched: list[str] = []
        missing: list[str] = []
        for skill in profile.skills:
            aliases = [skill, *profile.skill_aliases.get(skill, [])]
            if any(alias.lower() in text for alias in aliases):
                matched.append(skill)
            else:
                missing.append(skill)

        skills_score = round(100 * len(matched) / max(1, len(profile.skills)))
        role_hits = sum(role.lower() in text for role in profile.target_roles)
        role_score = min(100, role_hits * 50)
        if not role_hits and any(term in text for term in ("llm", "rag", "ai", "ии")):
            role_score = 40
        conditions_score = self._conditions_score(vacancy, profile)

        weighted = round(skills_score * 0.55 + role_score * 0.25 + conditions_score * 0.20)
        passed = not rejection_reasons
        total = weighted if passed else min(weighted, 39)
        explanation = self._explain(total, matched, missing, rejection_reasons)
        return ScoreResult(
            total_score=total,
            hard_skills_score=skills_score,
            role_score=role_score,
            conditions_score=conditions_score,
            passed_hard_filters=passed,
            matched_skills=matched,
            missing_skills=missing,
            rejection_reasons=rejection_reasons,
            explanation=explanation,
        )

    @staticmethod
    def _hard_filter_reasons(
        vacancy: Vacancy, profile: CandidateProfile, text: str
    ) -> list[str]:
        reasons: list[str] = []
        has_required_terms = all(term.lower() in text for term in profile.required_terms)
        if profile.required_terms and not has_required_terms:
            reasons.append("Не найдены все обязательные ключевые слова")
        found_excluded = [term for term in profile.excluded_terms if term.lower() in text]
        if found_excluded:
            reasons.append(f"Исключённые направления: {', '.join(found_excluded)}")
        if profile.allowed_area_ids and vacancy.area_id not in profile.allowed_area_ids:
            reasons.append("Регион не входит в список допустимых")
        if profile.remote_only and vacancy.schedule_id != "remote":
            reasons.append("Требуется удалённый формат")
        if (
            profile.accepted_experience_ids
            and vacancy.experience_id not in profile.accepted_experience_ids
        ):
            reasons.append("Не подходит требуемый опыт")
        if profile.minimum_salary is not None:
            salary_floor = vacancy.salary_from or vacancy.salary_to
            if (
                salary_floor is not None
                and vacancy.salary_currency == profile.salary_currency
                and salary_floor < profile.minimum_salary
            ):
                reasons.append("Зарплата ниже заданного минимума")
        return reasons

    @staticmethod
    def _conditions_score(vacancy: Vacancy, profile: CandidateProfile) -> int:
        score = 70
        if vacancy.salary_from is not None:
            score += 10
        if vacancy.schedule_id == "remote":
            score += 10
        if vacancy.experience_id in profile.accepted_experience_ids:
            score += 10
        return min(score, 100)

    @staticmethod
    def _explain(
        total: int, matched: list[str], missing: list[str], rejection_reasons: list[str]
    ) -> str:
        if rejection_reasons:
            return f"{total}/100: вакансия не прошла жёсткие фильтры. {rejection_reasons[0]}."
        strengths = ", ".join(matched[:4]) or "явных совпадений навыков нет"
        gap = f" Основные пробелы: {', '.join(missing[:3])}." if missing else ""
        return f"{total}/100: совпадения — {strengths}.{gap}"
