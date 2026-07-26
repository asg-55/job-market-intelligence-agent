from __future__ import annotations

import re
from typing import Any, AsyncIterator

import httpx

from .config import SearchQuery
from .domain import Vacancy

_TAG_RE = re.compile(r"<[^>]+>")


class HHClient:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        access_token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        headers = {"HH-User-Agent": user_agent, "Accept": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=20
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(self, query: SearchQuery, pages: int = 1) -> AsyncIterator[Vacancy]:
        for page in range(pages):
            params: dict[str, Any] = {
                "text": query.text,
                "period": query.period,
                "page": page,
                "per_page": 50,
            }
            if query.area:
                params["area"] = query.area
            response = await self._client.get("/vacancies", params=params)
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("items", []):
                yield await self.get_vacancy(str(item["id"]))
            if page >= payload.get("pages", 1) - 1:
                break

    async def get_vacancy(self, vacancy_id: str) -> Vacancy:
        response = await self._client.get(f"/vacancies/{vacancy_id}")
        response.raise_for_status()
        return parse_vacancy(response.json())


def parse_vacancy(data: dict[str, Any]) -> Vacancy:
    salary = data.get("salary") or {}
    area = data.get("area") or {}
    experience = data.get("experience") or {}
    employment = data.get("employment") or {}
    schedule = data.get("schedule") or {}
    employer = data.get("employer") or {}
    description = _TAG_RE.sub(" ", data.get("description") or "")
    description = re.sub(r"\s+", " ", description).strip()
    return Vacancy(
        id=str(data["id"]),
        name=data.get("name") or "Без названия",
        employer=employer.get("name") or "Не указана",
        area_id=str(area["id"]) if area.get("id") is not None else None,
        area_name=area.get("name"),
        experience_id=experience.get("id"),
        experience_name=experience.get("name"),
        employment_name=employment.get("name"),
        schedule_id=schedule.get("id"),
        schedule_name=schedule.get("name"),
        salary_from=salary.get("from"),
        salary_to=salary.get("to"),
        salary_currency=salary.get("currency"),
        salary_gross=salary.get("gross"),
        description=description,
        key_skills=[skill["name"] for skill in data.get("key_skills", [])],
        url=data.get("alternate_url") or f"https://hh.ru/vacancy/{data['id']}",
        published_at=data.get("published_at"),
        raw=data,
    )
