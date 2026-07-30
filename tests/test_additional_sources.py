import asyncio

import httpx
import pytest

from job_copilot.config import SearchQuery
from job_copilot.jooble import JoobleClient, parse_jooble_vacancy
from job_copilot.sources import SourceAPIError
from job_copilot.superjob import SuperJobClient, parse_superjob_vacancy


def test_superjob_parser_adds_stable_source_prefix() -> None:
    vacancy = parse_superjob_vacancy(
        {
            "id": 77,
            "profession": "Python-разработчик",
            "firm_name": "Пример",
            "town": {"id": 4, "title": "Томск"},
            "place_of_work": {"title": "Удаленная работа"},
            "payment_from": 150000,
            "currency": "rub",
            "candidat": "Python, FastAPI и интеграции",
            "link": "https://www.superjob.ru/vakansii/77.html",
        }
    )

    assert vacancy.id == "superjob:77"
    assert vacancy.source == "superjob"
    assert vacancy.schedule_id == "remote"
    assert vacancy.salary_from == 150000


def test_jooble_parser_detects_remote_job() -> None:
    vacancy = parse_jooble_vacancy(
        {
            "id": "abc",
            "title": "AI Engineer",
            "company": "Example",
            "location": "Remote",
            "snippet": "<b>Build</b> RAG services",
            "link": "https://example.com/job/abc",
        }
    )

    assert vacancy.id == "jooble:abc"
    assert vacancy.source == "jooble"
    assert vacancy.schedule_id == "remote"
    assert vacancy.description == "Build RAG services"


def test_superjob_client_sends_secret_header() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-Api-App-Id"] == "secret"
            return httpx.Response(200, json={"objects": [], "more": False}, request=request)

        async_client = httpx.AsyncClient(
            base_url="https://api.superjob.ru/2.0", transport=httpx.MockTransport(handler)
        )
        client = SuperJobClient("secret", client=async_client)
        assert [item async for item in client.search(SearchQuery(text="Python"))] == []
        await async_client.aclose()

    asyncio.run(scenario())

def test_jooble_client_exposes_invalid_key_safely() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "denied"}, request=request)

        async_client = httpx.AsyncClient(
            base_url="https://jooble.org/api", transport=httpx.MockTransport(handler)
        )
        client = JoobleClient("bad-key", client=async_client)
        with pytest.raises(SourceAPIError) as raised:
            await anext(client.search(SearchQuery(text="Python")))
        assert raised.value.category == "authorization"
        assert "JOOBLE_API_KEY" in raised.value.user_message
        await async_client.aclose()

    asyncio.run(scenario())
