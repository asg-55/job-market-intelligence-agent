from __future__ import annotations

import html
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .config import SearchQuery
from .domain import Vacancy

_TAG_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"[\w+#.-]{3,}", re.UNICODE)
_QUERY_OPERATORS = {"and", "or", "not", "или", "и"}


class RemotiveClient:
    """Read-only adapter for Remotive's public, delayed remote-jobs feed."""

    source_name = "remotive"

    def __init__(
        self,
        base_url: str = "https://remotive.com/api",
        *,
        cache_hours: int = 6,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=30)
        self._owns_client = client is None
        self._cache_ttl = timedelta(hours=cache_hours)
        self._cached_at: datetime | None = None
        self._cached_jobs: list[dict[str, Any]] | None = None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(self, query: SearchQuery, pages: int = 1) -> AsyncIterator[Vacancy]:
        del pages
        jobs = await self._get_jobs()
        terms = [
            term.lower()
            for term in _WORD_RE.findall(query.text)
            if term.lower() not in _QUERY_OPERATORS
        ]
        for job in jobs:
            vacancy = parse_remotive_vacancy(job)
            haystack = vacancy.searchable_text()
            if not terms or any(term in haystack for term in terms):
                yield vacancy

    async def _get_jobs(self) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        if (
            self._cached_jobs is not None
            and self._cached_at is not None
            and now - self._cached_at < self._cache_ttl
        ):
            return self._cached_jobs
        response = await self._client.get("/remote-jobs", params={"limit": 500})
        response.raise_for_status()
        jobs = response.json().get("jobs", [])
        self._cached_jobs = jobs if isinstance(jobs, list) else []
        self._cached_at = now
        return self._cached_jobs


def parse_remotive_vacancy(data: dict[str, Any]) -> Vacancy:
    description = html.unescape(_TAG_RE.sub(" ", data.get("description") or ""))
    description = re.sub(r"\s+", " ", description).strip()
    location = data.get("candidate_required_location") or "Remote"
    job_id = str(data["id"])
    return Vacancy(
        id=f"remotive:{job_id}",
        name=data.get("title") or "Untitled role",
        employer=data.get("company_name") or "Not specified",
        area_id=None,
        area_name=location,
        experience_id=None,
        experience_name=None,
        employment_name=data.get("job_type"),
        schedule_id="remote",
        schedule_name=f"Remote · {location}",
        salary_from=None,
        salary_to=None,
        salary_currency=None,
        salary_gross=None,
        description=description,
        key_skills=[str(tag) for tag in data.get("tags", [])],
        url=data.get("url") or f"https://remotive.com/remote-jobs/{job_id}",
        published_at=data.get("publication_date"),
        raw=data,
        source="remotive",
    )
