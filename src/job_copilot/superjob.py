from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx

from .config import SearchQuery
from .domain import Vacancy
from .sources import SourceAPIError


class SuperJobClient:
    source_name = "superjob"

    def __init__(
        self,
        secret_key: str,
        base_url: str = "https://api.superjob.ru/2.0",
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._headers = {"X-Api-App-Id": secret_key, "Accept": "application/json"}
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=30)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(self, query: SearchQuery, pages: int = 1) -> AsyncIterator[Vacancy]:
        for page in range(pages):
            response = await self._client.get(
                "/vacancies/",
                params={"keyword": query.text, "page": page, "count": 100},
                headers=self._headers,
            )
            _raise_for_status(response, "SuperJob")
            payload = response.json()
            for item in payload.get("objects", []):
                yield parse_superjob_vacancy(item)
            if not payload.get("more"):
                break


def _raise_for_status(response: httpx.Response, source: str) -> None:
    if response.status_code in {401, 403}:
        raise SourceAPIError(
            "authorization", f"Ключ {source} недействителен. Проверьте его в локальном .env."
        )
    if response.status_code == 429:
        raise SourceAPIError(
            "rate_limit", f"{source} ограничил частоту запросов. Повторим по расписанию."
        )
    response.raise_for_status()


def parse_superjob_vacancy(data: dict[str, Any]) -> Vacancy:
    town = data.get("town") or {}
    experience = data.get("experience") or {}
    work_type = data.get("type_of_work") or {}
    place = data.get("place_of_work") or {}
    published = data.get("date_published")
    published_at = (
        datetime.fromtimestamp(published, UTC).isoformat() if isinstance(published, int) else None
    )
    description = re.sub(r"\s+", " ", data.get("candidat") or "").strip()
    return Vacancy(
        id=f"superjob:{data['id']}",
        name=data.get("profession") or "Без названия",
        employer=data.get("firm_name") or "Не указана",
        area_id=str(town["id"]) if town.get("id") is not None else None,
        area_name=town.get("title"),
        experience_id=_normalize_experience(experience.get("title")),
        experience_name=experience.get("title"),
        employment_name=work_type.get("title"),
        schedule_id="remote" if "удален" in str(place.get("title", "")).lower() else None,
        schedule_name=place.get("title"),
        salary_from=data.get("payment_from") or None,
        salary_to=data.get("payment_to") or None,
        salary_currency="RUR" if data.get("currency") == "rub" else data.get("currency"),
        salary_gross=None,
        description=description,
        key_skills=[],
        url=data.get("link") or f"https://www.superjob.ru/vakansii/{data['id']}.html",
        published_at=published_at,
        raw=data,
        source="superjob",
    )


def _normalize_experience(title: str | None) -> str | None:
    normalized = (title or "").lower()
    if "без опыта" in normalized:
        return "noExperience"
    numbers = [int(item) for item in re.findall(r"\d+", normalized)]
    if not numbers:
        return None
    minimum = numbers[0]
    if minimum < 3:
        return "between1And3"
    if minimum < 6:
        return "between3And6"
    return "moreThan6"
