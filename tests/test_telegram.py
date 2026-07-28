import asyncio
import json

import httpx
from test_scoring import profile, vacancy

from job_copilot.config import SearchProfile
from job_copilot.scoring import ExplainableScorer
from job_copilot.telegram import TelegramNotifier


def _send_and_capture(
    feedback_enabled: bool, search_profile: SearchProfile | None = None
) -> dict:
    captured: dict = {}

    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {}})

        client = httpx.AsyncClient(
            base_url="https://api.telegram.test/bot-token",
            transport=httpx.MockTransport(handler),
        )
        notifier = TelegramNotifier(
            "token", "123", client=client, feedback_enabled=feedback_enabled
        )
        item = vacancy()
        result = ExplainableScorer().score(item, profile())
        await notifier.send_vacancy(item, result, search_profile)
        await client.aclose()

    asyncio.run(scenario())
    return captured


def test_feedback_buttons_are_hidden_without_webhook() -> None:
    payload = _send_and_capture(feedback_enabled=False)
    rows = payload["reply_markup"]["inline_keyboard"]
    assert len(rows) == 1
    assert rows[0][0]["text"] == "Открыть вакансию"


def test_feedback_buttons_are_enabled_with_webhook() -> None:
    payload = _send_and_capture(feedback_enabled=True)
    rows = payload["reply_markup"]["inline_keyboard"]
    assert len(rows) == 2
    assert rows[1][0]["callback_data"] == "fit:42"


def test_search_profile_and_resume_are_shown_in_message() -> None:
    payload = _send_and_capture(
        feedback_enabled=False,
        search_profile=SearchProfile(
            key="ai-product",
            name="AI Product",
            resume_id=7,
            searches=[{"text": "AI product engineer"}],
        ),
    )

    assert "Профиль поиска: <b>AI Product</b> · резюме #7" in payload["text"]
