import asyncio

import httpx
import pytest

from job_copilot.config import SearchQuery
from job_copilot.hh import HHAPIError, HHClient, classify_hh_error, parse_vacancy


def test_parse_vacancy_removes_html() -> None:
    parsed = parse_vacancy(
        {
            "id": "1",
            "name": "Engineer",
            "description": "<p>Build <strong>AI</strong></p>",
            "employer": {"name": "Acme"},
            "area": {"id": "2", "name": "СПб"},
            "key_skills": [{"name": "Python"}],
        }
    )
    assert parsed.description == "Build AI"
    assert parsed.key_skills == ["Python"]
    assert parsed.url == "https://hh.ru/vacancy/1"


@pytest.mark.parametrize(
    ("status", "errors", "category"),
    [
        (403, [{"type": "captcha_required"}], "captcha"),
        (403, [{"type": "oauth", "value": "token_expired"}], "authorization"),
        (403, [{"type": "forbidden"}], "forbidden"),
        (429, [], "rate_limit"),
        (503, [], "unavailable"),
    ],
)
def test_hh_errors_are_classified(status, errors, category) -> None:
    response = httpx.Response(
        status,
        json={"errors": errors},
        request=httpx.Request("GET", "https://api.hh.ru/vacancies"),
    )

    actual, message = classify_hh_error(response)

    assert actual == category
    assert message


def test_hh_client_sends_application_token_and_exposes_safe_error() -> None:
    async def scenario() -> None:
        captured: httpx.Request | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured
            captured = request
            return httpx.Response(
                403,
                json={"errors": [{"type": "captcha_required"}]},
                request=request,
            )

        async_client = httpx.AsyncClient(
            base_url="https://api.hh.ru", transport=httpx.MockTransport(handler)
        )
        client = HHClient(
            "https://api.hh.ru",
            "JobCopilot/0.1 (test@example.com)",
            "application-token",
            client=async_client,
        )
        with pytest.raises(HHAPIError) as raised:
            await anext(client.search(SearchQuery(text="AI")))

        assert raised.value.category == "captcha"
        assert captured is not None
        assert captured.headers["Authorization"] == "Bearer application-token"
        assert captured.headers["HH-User-Agent"] == "JobCopilot/0.1 (test@example.com)"
        await async_client.aclose()

    asyncio.run(scenario())
