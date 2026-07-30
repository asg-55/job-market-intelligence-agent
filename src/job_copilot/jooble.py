from __future__ import annotations

import re
from collections.abc import AsyncIterator
from hashlib import sha256
from typing import Any

import httpx

from .config import SearchQuery
from .domain import Vacancy
from .sources import SourceAPIError


class JoobleClient:
    source_name = "jooble"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://jooble.org/api",
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=30)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(self, query: SearchQuery, pages: int = 1) -> AsyncIterator[Vacancy]:
        for page in range(1, pages + 1):
            response = await self._client.post(
                f"/{self._api_key}",
                json={"keywords": query.text, "page": page, "ResultOnPage": 50},
            )
            if response.status_code in {401, 403}:
                raise SourceAPIError(
                    "authorization", "Ключ Jooble недействителен. Проверьте JOOBLE_API_KEY."
                )
            if response.status_code == 429:
                raise SourceAPIError(
                    "rate_limit", "Jooble ограничил частоту запросов. Повторим по расписанию."
                )
            response.raise_for_status()
            jobs = response.json().get("jobs", [])
            for item in jobs:
                yield parse_jooble_vacancy(item)
            if len(jobs) < 50:
                break


def parse_jooble_vacancy(data: dict[str, Any]) -> Vacancy:
    description = re.sub(r"<[^>]+>", " ", data.get("snippet") or "")
    description = re.sub(r"\s+", " ", description).strip()
    location = data.get("location")
    job_type = data.get("type")
    work_context = f"{location} {job_type}".lower()
    remote = "remote" in work_context or "удален" in work_context
    job_id = str(data.get("id") or sha256(str(data.get("link")).encode()).hexdigest()[:20])
    return Vacancy(
        id=f"jooble:{job_id}",
        name=data.get("title") or "Без названия",
        employer=data.get("company") or "Не указана",
        area_id=None,
        area_name=location,
        experience_id=None,
        experience_name=None,
        employment_name=job_type,
        schedule_id="remote" if remote else None,
        schedule_name="Удалённо" if remote else job_type,
        salary_from=None,
        salary_to=None,
        salary_currency=None,
        salary_gross=None,
        description=description,
        key_skills=[],
        url=data.get("link") or "https://jooble.org/",
        published_at=data.get("updated"),
        raw=data,
        source="jooble",
    )
