from __future__ import annotations

import html

import httpx

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
        self._client = client or httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{token}", timeout=20
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def send_vacancy(self, vacancy: Vacancy, result: ScoreResult) -> None:
        strengths = ", ".join(result.matched_skills[:5]) or "нет явных совпадений"
        gaps = ", ".join(result.missing_skills[:3]) or "критичных не найдено"
        message = (
            f"🔥 <b>Совпадение: {result.total_score}%</b>\n\n"
            f"<b>{html.escape(vacancy.name)}</b>\n"
            f"Компания: {html.escape(vacancy.employer)}\n"
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
            "/sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": {"inline_keyboard": rows},
            },
        )
        response.raise_for_status()

    async def answer_callback(self, callback_query_id: str, text: str) -> None:
        response = await self._client.post(
            "/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
        )
        response.raise_for_status()
