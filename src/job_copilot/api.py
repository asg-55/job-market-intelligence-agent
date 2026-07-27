from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import sha256
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .bootstrap import AppContainer, build_container
from .config import CandidateProfile, get_settings


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


class ProfileResponse(BaseModel):
    profile: CandidateProfile
    version: str


class CoverLetterRequest(BaseModel):
    language: Literal["ru", "en"] = "ru"
    tone: Literal["professional", "concise", "warm"] = "professional"


class CoverLetterResponse(BaseModel):
    id: int
    vacancy_id: str
    profile_version: str
    status: Literal["draft"] = "draft"
    text: str
    fact_trace: list[dict[str, Any]]
    metadata: dict[str, Any]


class ResumeAdviceRequest(BaseModel):
    resume_text: str = Field(min_length=50, max_length=30_000)
    language: Literal["ru", "en"] = "ru"


class ResumeAdviceResponse(BaseModel):
    id: int
    vacancy_id: str
    profile_version: str
    resume_sha256: str
    status: Literal["draft"] = "draft"
    result: dict[str, Any]
    metadata: dict[str, Any]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/vacancies")
def vacancies(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    return container(request).repository.list_vacancies(limit)


@app.get("/profile")
def get_profile(request: Request) -> ProfileResponse:
    profile = container(request).profile_store.load()
    return ProfileResponse(profile=profile, version=profile.fingerprint())


@app.put("/profile")
def replace_profile(profile: CandidateProfile, request: Request) -> ProfileResponse:
    saved = container(request).profile_store.save(profile)
    return ProfileResponse(profile=saved, version=saved.fingerprint())


@app.patch("/profile")
def update_profile(
    request: Request, changes: Annotated[dict[str, Any], Body(min_length=1)]
) -> ProfileResponse:
    saved = container(request).profile_store.patch(changes)
    return ProfileResponse(profile=saved, version=saved.fingerprint())


@app.post("/monitor/run")
async def run_monitor(request: Request, pages: int = Query(default=1, ge=1, le=10)):
    current = container(request)
    return await current.pipeline.run(current.profile_store.load(), pages=pages)


@app.post("/vacancies/{vacancy_id}/feedback", status_code=204)
def feedback(vacancy_id: str, payload: FeedbackRequest, request: Request) -> None:
    current = container(request)
    if not current.repository.has_vacancy(vacancy_id):
        raise HTTPException(status_code=404, detail="Vacancy not found")
    current.repository.add_feedback(vacancy_id, payload.action, payload.note)


@app.post("/vacancies/{vacancy_id}/cover-letter", response_model=CoverLetterResponse)
async def generate_cover_letter(
    vacancy_id: str, payload: CoverLetterRequest, request: Request
) -> CoverLetterResponse:
    current = container(request)
    vacancy = current.repository.get_vacancy(vacancy_id)
    if vacancy is None:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    if current.cover_letter_generator is None:
        raise HTTPException(status_code=503, detail="Configure LLM_MODEL first")

    profile = current.profile_store.load()
    try:
        generated = await current.cover_letter_generator.generate(
            vacancy, profile, language=payload.language, tone=payload.tone
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    profile_version = profile.fingerprint()
    fact_trace = [item.model_dump() for item in generated.fact_trace]
    metadata = {
        "model": generated.model,
        "prompt_version": generated.prompt_version,
        "usage": generated.usage,
        "language": payload.language,
        "tone": payload.tone,
    }
    draft_id = current.repository.save_cover_letter(
        vacancy_id, profile_version, generated.text, fact_trace, metadata
    )
    return CoverLetterResponse(
        id=draft_id,
        vacancy_id=vacancy_id,
        profile_version=profile_version,
        text=generated.text,
        fact_trace=fact_trace,
        metadata=metadata,
    )


@app.get("/cover-letters/{draft_id}", response_model=CoverLetterResponse)
def get_cover_letter(draft_id: int, request: Request) -> CoverLetterResponse:
    draft = container(request).repository.get_cover_letter(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Cover-letter draft not found")
    draft["text"] = draft.pop("content")
    return CoverLetterResponse.model_validate(draft)


@app.post("/vacancies/{vacancy_id}/resume-advice", response_model=ResumeAdviceResponse)
async def generate_resume_advice(
    vacancy_id: str, payload: ResumeAdviceRequest, request: Request
) -> ResumeAdviceResponse:
    current = container(request)
    vacancy = current.repository.get_vacancy(vacancy_id)
    if vacancy is None:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    if current.resume_advisor is None:
        raise HTTPException(status_code=503, detail="Configure LLM_MODEL first")

    profile = current.profile_store.load()
    try:
        generated = await current.resume_advisor.generate(
            vacancy, profile, payload.resume_text, language=payload.language
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    profile_version = profile.fingerprint()
    resume_hash = f"sha256:{sha256(payload.resume_text.encode('utf-8')).hexdigest()}"
    result = generated.model_dump(
        exclude={"model", "prompt_version", "usage"}, mode="json"
    )
    metadata = {
        "model": generated.model,
        "prompt_version": generated.prompt_version,
        "usage": generated.usage,
        "language": payload.language,
        "source_resume_stored": False,
    }
    advice_id = current.repository.save_resume_advice(
        vacancy_id, profile_version, resume_hash, result, metadata
    )
    return ResumeAdviceResponse(
        id=advice_id,
        vacancy_id=vacancy_id,
        profile_version=profile_version,
        resume_sha256=resume_hash,
        result=result,
        metadata=metadata,
    )


@app.get("/resume-advice/{advice_id}", response_model=ResumeAdviceResponse)
def get_resume_advice(advice_id: int, request: Request) -> ResumeAdviceResponse:
    advice = container(request).repository.get_resume_advice(advice_id)
    if advice is None:
        raise HTTPException(status_code=404, detail="Resume advice not found")
    return ResumeAdviceResponse.model_validate(advice)


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
