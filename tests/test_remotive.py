import asyncio

import httpx

from job_copilot.config import SearchQuery
from job_copilot.remotive import RemotiveClient, parse_remotive_vacancy


def remotive_job(**overrides):
    values = {
        "id": 101,
        "title": "AI Engineer",
        "company_name": "Example Labs",
        "candidate_required_location": "Worldwide",
        "job_type": "full_time",
        "publication_date": "2026-07-30T12:00:00",
        "description": "<p>Build <strong>Python RAG</strong> services</p>",
        "tags": ["Python", "AI"],
        "url": "https://remotive.com/remote-jobs/software-dev/ai-engineer-101",
    }
    values.update(overrides)
    return values


def test_parse_remotive_vacancy_normalizes_source_and_remote_schedule() -> None:
    vacancy = parse_remotive_vacancy(remotive_job())

    assert vacancy.id == "remotive:101"
    assert vacancy.source == "remotive"
    assert vacancy.schedule_id == "remote"
    assert vacancy.area_name == "Worldwide"
    assert vacancy.description == "Build Python RAG services"


def test_remotive_client_fetches_feed_once_and_filters_locally() -> None:
    async def scenario() -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            assert request.url.path == "/api/remote-jobs"
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        remotive_job(),
                        remotive_job(
                            id=102,
                            title="Finance Manager",
                            description="Manage financial reporting",
                            tags=["Finance"],
                        ),
                    ]
                },
                request=request,
            )

        async_client = httpx.AsyncClient(
            base_url="https://remotive.com/api", transport=httpx.MockTransport(handler)
        )
        client = RemotiveClient(client=async_client)

        ai_jobs = [item async for item in client.search(SearchQuery(text="AI Python"))]
        finance_jobs = [
            item async for item in client.search(SearchQuery(text="Finance Manager"))
        ]

        assert [item.id for item in ai_jobs] == ["remotive:101"]
        assert [item.id for item in finance_jobs] == ["remotive:102"]
        assert calls == 1
        await async_client.aclose()

    asyncio.run(scenario())
