from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .bootstrap import AppContainer, build_container
from .config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = build_container(get_settings())
    app.state.container = container
    yield
    await container.close()


app = FastAPI(
    title="AI Job Search Copilot",
    version="0.1.0",
    description="Explainable vacancy monitoring and matching service",
    lifespan=lifespan,
)


def container(request: Request) -> AppContainer:
    return request.app.state.container


class FeedbackRequest(BaseModel):
    action: str = Field(pattern="^(fit|skip|applied|rejected|interview)$")
    note: str | None = Field(default=None, max_length=1000)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/vacancies")
def vacancies(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    return container(request).repository.list_vacancies(limit)


@app.post("/monitor/run")
async def run_monitor(request: Request, pages: int = Query(default=1, ge=1, le=10)):
    current = container(request)
    return await current.pipeline.run(current.profile, pages=pages)


@app.post("/vacancies/{vacancy_id}/feedback", status_code=204)
def feedback(vacancy_id: str, payload: FeedbackRequest, request: Request) -> None:
    current = container(request)
    if not current.repository.has_vacancy(vacancy_id):
        raise HTTPException(status_code=404, detail="Vacancy not found")
    current.repository.add_feedback(vacancy_id, payload.action, payload.note)


@app.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    current = container(request)
    expected_secret = current.settings.telegram_webhook_secret
    if not expected_secret or x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    payload = await request.json()
    callback = payload.get("callback_query")
    if not callback or not current.notifier:
        return {"ok": True}
    try:
        action, vacancy_id = callback.get("data", "").split(":", maxsplit=1)
    except ValueError:
        await current.notifier.answer_callback(callback["id"], "Неизвестное действие")
        return {"ok": True}
    if action not in {"fit", "skip"} or not current.repository.has_vacancy(vacancy_id):
        await current.notifier.answer_callback(callback["id"], "Вакансия не найдена")
        return {"ok": True}
    current.repository.add_feedback(vacancy_id, action)
    label = "Сохранил: подходит" if action == "fit" else "Сохранил: не подходит"
    await current.notifier.answer_callback(callback["id"], label)
    return {"ok": True}
