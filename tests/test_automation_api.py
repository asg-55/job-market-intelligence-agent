import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import httpx

from job_copilot.api import app
from job_copilot.config import CandidateProfile, Settings
from job_copilot.pipeline import RunSummary


class ProfileStoreStub:
    def load(self) -> CandidateProfile:
        return CandidateProfile(name="Alex", skills=["Python"])


class PipelineStub:
    def __init__(self) -> None:
        self.pages: list[int] = []

    async def run(self, profile: CandidateProfile, pages: int = 1) -> dict:
        assert profile.name == "Alex"
        self.pages.append(pages)
        return asdict(RunSummary(found=4, new=2, notified=1))


def test_automation_routes_require_shared_token() -> None:
    async def scenario() -> None:
        pipeline = PipelineStub()
        app.state.container = SimpleNamespace(
            settings=Settings(automation_api_token="local-secret", llm_model="qwen3.5:9b"),
            profile_store=ProfileStoreStub(),
            pipeline=pipeline,
            notifier=object(),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            missing = await client.post("/automation/monitor/run?pages=2")
            invalid = await client.get(
                "/automation/status", headers={"X-Automation-Token": "wrong"}
            )
            status = await client.get(
                "/automation/status", headers={"X-Automation-Token": "local-secret"}
            )
            run = await client.post(
                "/automation/monitor/run?pages=2",
                headers={"X-Automation-Token": "local-secret"},
            )

        assert missing.status_code == 401
        assert invalid.status_code == 401
        assert status.status_code == 200
        assert status.json()["llm"] is True
        assert status.json()["telegram"] is True
        assert status.json()["hh_authenticated"] is False
        assert run.status_code == 200
        assert run.json()["notified"] == 1
        assert pipeline.pages == [2]

    asyncio.run(scenario())


def test_automation_routes_are_disabled_without_configured_token() -> None:
    async def scenario() -> None:
        app.state.container = SimpleNamespace(
            settings=Settings(automation_api_token=None),
            profile_store=ProfileStoreStub(),
            pipeline=PipelineStub(),
            notifier=None,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/automation/status", headers={"X-Automation-Token": "anything"}
            )

        assert response.status_code == 503

    asyncio.run(scenario())
