from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import SearchQuery
from .domain import Vacancy

_TAG_RE = re.compile(r"<[^>]+>")


class HHAPIError(httpx.HTTPStatusError):
    def __init__(
        self,
        message: str,
        *,
        category: str,
        user_message: str,
        request: httpx.Request,
        response: httpx.Response,
    ) -> None:
        super().__init__(message, request=request, response=response)
        self.category = category
        self.user_message = user_message


class HHClient:
    source_name = "hh"

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
        self._headers = headers
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=20)
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
            response = await self._get("/vacancies", params=params)
            payload = response.json()
            for item in payload.get("items", []):
                yield await self.get_vacancy(str(item["id"]))
            if page >= payload.get("pages", 1) - 1:
                break

    async def get_vacancy(self, vacancy_id: str) -> Vacancy:
        response = await self._get(f"/vacancies/{vacancy_id}")
        return parse_vacancy(response.json())

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        response = await self._client.get(path, params=params, headers=self._headers)
        if response.is_success:
            return response
        category, user_message = classify_hh_error(response)
        raise HHAPIError(
            f"HH API returned {response.status_code}",
            category=category,
            user_message=user_message,
            request=response.request,
            response=response,
        )


def classify_hh_error(response: httpx.Response) -> tuple[str, str]:
    error_markers: set[str] = set()
    try:
        payload = response.json()
        for error in payload.get("errors", []):
            error_markers.add(str(error.get("type", "")).lower())
            error_markers.add(str(error.get("value", "")).lower())
    except (TypeError, ValueError):
        pass

    if response.status_code == 403 and any("captcha" in item for item in error_markers):
        return (
            "captcha",
            "HH временно требует CAPTCHA. Откройте hh.ru, войдите в аккаунт и "
            "пройдите проверку, затем повторите поиск.",
        )
    if response.status_code == 403 and (
        "oauth" in error_markers
        or any("authorization" in item or "token" in item for item in error_markers)
    ):
        return (
            "authorization",
            "Токен HH недействителен или истёк. Обновите HH_ACCESS_TOKEN в .env.",
        )
    if response.status_code == 403:
        return (
            "forbidden",
            "HH отклонил запрос. Зарегистрируйте приложение на dev.hh.ru и настройте "
            "HH_ACCESS_TOKEN.",
        )
    if response.status_code == 429:
        return (
            "rate_limit",
            "HH ограничил частоту запросов. Не запускайте поиск вручную — следующая "
            "попытка будет выполнена по расписанию.",
        )
    if response.status_code >= 500:
        return "unavailable", "Сервис HH временно недоступен. Повторим попытку по расписанию."
    return "http_error", f"HH вернул ошибку HTTP {response.status_code}."


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
        source="hh",
    )
