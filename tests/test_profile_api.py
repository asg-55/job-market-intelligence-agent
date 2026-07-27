import asyncio
from types import SimpleNamespace

import httpx

from job_copilot.api import app
from job_copilot.config import CandidateProfile
from job_copilot.profile_store import ProfileStore


def test_profile_can_be_changed_through_api_without_restart(tmp_path) -> None:
    async def scenario() -> None:
        store = ProfileStore(tmp_path / "profile.json")
        store.save(CandidateProfile(name="Alex", skills=["Python"]))
        app.state.container = SimpleNamespace(profile_store=store)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            before = await client.get("/profile")
            changed = await client.patch("/profile", json={"remote_only": True})
            after = await client.get("/profile")

        assert before.status_code == 200
        assert changed.status_code == 200
        assert changed.json()["profile"]["remote_only"] is True
        assert after.json()["profile"]["name"] == "Alex"
        assert after.json()["version"] != before.json()["version"]

    asyncio.run(scenario())
