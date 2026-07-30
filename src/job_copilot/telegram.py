from __future__ import annotations

import html

import httpx

from .config import SearchProfile
from .domain import ScoreResult, Vacancy


class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_id: str,
        client: httpx.AsyncClient | None = None,
        *,
        feedback_enabled: bool = False,
    ) -> None:
        self.chat_id = chat_id
        self.feedback_enabled = feedback_enabled
        self._token = token
        self._client = client or httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{token}/", timeout=20
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def send_vacancy(
        self,
        vacancy: Vacancy,
        result: ScoreResult,
        search_profile: SearchProfile | None = None,
    ) -> None:
        strengths = ", ".join(result.matched_skills[:5]) or "нет явных совпадений"
        gaps = ", ".join(result.missing_skills[:3]) or "критичных не найдено"
        search_context = ""
        if search_profile is not None:
            resume_hint = (
                f" · резюме #{search_profile.resume_id}" if search_profile.resume_id else ""
            )
            search_context = (
                f"Профиль поиска: <b>{html.escape(search_profile.name)}</b>"
                f"{resume_hint}\n"
            )
        message = (
            f"🔥 <b>Совпадение: {result.total_score}%</b>\n\n"
            f"<b>{html.escape(vacancy.name)}</b>\n"
            f"Компания: {html.escape(vacancy.employer)}\n"
            f"Источник: {html.escape(vacancy.source.title())}\n"
            f"{search_context}"
            f"Формат: {html.escape(vacancy.schedule_name or 'не указан')}\n"
            f"Опыт: {html.escape(vacancy.experience_name or 'не указан')}\n\n"
            f"<b>Совпало:</b> {html.escape(strengths)}\n"
            f"<b>Пробелы:</b> {html.escape(gaps)}"
        )
        rows = [[{"text": "Открыть вакансию", "url": vacancy.url}]]
        if self.feedback_enabled:
            rows.append(
                [
                    {"text": "👍 Подходит", "callback_data": f"fit:{vacancy.id}"},
                    {"text": "👎 Не подходит", "callback_data": f"skip:{vacancy.id}"},
                ]
            )
        response = await self._client.post(
            "sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": {"inline_keyboard": rows},
            },
        )
        response.raise_for_status()

    async def send_text(self, text: str, reply_markup: dict | None = None) -> None:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        response = await self._client.post("sendMessage", json=payload)
        response.raise_for_status()

    async def download_file(self, file_id: str) -> bytes:
        response = await self._client.post("getFile", json={"file_id": file_id})
        response.raise_for_status()
        file_path = response.json()["result"]["file_path"]
        download = await self._client.get(
            f"https://api.telegram.org/file/bot{self._token}/{file_path}"
        )
        download.raise_for_status()
        return download.content

    async def get_updates(self, offset: int | None = None) -> list[dict]:
        params: dict[str, int] = {"timeout": 25}
        if offset is not None:
            params["offset"] = offset
        response = await self._client.get("getUpdates", params=params, timeout=35)
        response.raise_for_status()
        return response.json().get("result", [])

    async def answer_callback(self, callback_query_id: str, text: str) -> None:
        response = await self._client.post(
            "answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
        )
        response.raise_for_status()
