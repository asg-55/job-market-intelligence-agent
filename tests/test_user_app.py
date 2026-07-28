import asyncio

import httpx

from job_copilot.api import app


def test_user_app_and_assets_are_served() -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            page = await client.get("/app")
            stylesheet = await client.get("/app-assets/app.css")
            script = await client.get("/app-assets/app.js")

        assert page.status_code == 200
        assert "Мои резюме" in page.text
        assert stylesheet.status_code == 200
        assert "--forest" in stylesheet.text
        assert script.status_code == 200
        assert "renderResumes" in script.text
        assert "openVacancy" in script.text
        assert "generate-advice" in page.text
        assert "run-monitor" in page.text

    asyncio.run(scenario())
