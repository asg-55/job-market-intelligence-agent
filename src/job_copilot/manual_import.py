from __future__ import annotations

from hashlib import sha256
from typing import Any

from .domain import Vacancy


def build_manual_vacancy(
    *,
    name: str,
    employer: str,
    description: str,
    url: str,
    source: str = "manual",
    remote: bool = False,
    key_skills: list[str] | None = None,
) -> Vacancy:
    normalized_source = "linkedin" if "linkedin.com" in url.lower() else source
    fingerprint = sha256(url.strip().encode("utf-8")).hexdigest()[:20]
    raw: dict[str, Any] = {"imported_manually": True}
    return Vacancy(
        id=f"{normalized_source}:{fingerprint}",
        name=name.strip(),
        employer=employer.strip(),
        area_id=None,
        area_name=None,
        experience_id=None,
        experience_name=None,
        employment_name=None,
        schedule_id="remote" if remote else None,
        schedule_name="Удалённо" if remote else None,
        salary_from=None,
        salary_to=None,
        salary_currency=None,
        salary_gross=None,
        description=description.strip(),
        key_skills=key_skills or [],
        url=url.strip(),
        published_at=None,
        raw=raw,
        source=normalized_source,
    )
