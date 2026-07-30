from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .bootstrap import AppContainer, build_container
from .config import CandidateProfile, get_settings
from .resume_export import build_resume_docx


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
WEB_DIR = Path(__file__).with_name("web")
app.mount("/app-assets", StaticFiles(directory=WEB_DIR), name="app-assets")


def container(request: Request) -> AppContainer:
    return request.app.state.container


def require_automation_token(
    request: Request,
    x_automation_token: Annotated[str | None, Header()] = None,
) -> AppContainer:
    current = container(request)
    expected = current.settings.automation_api_token
    if not expected:
        raise HTTPException(status_code=503, detail="Configure AUTOMATION_API_TOKEN first")
    if not x_automation_token or not compare_digest(x_automation_token, expected):
        raise HTTPException(status_code=401, detail="Invalid automation token")
    return current


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


class ResumeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_roles: list[str] = Field(default_factory=list, max_length=20)
    content: str = Field(min_length=50, max_length=30_000)


class ResumeUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_roles: list[str] | None = Field(default=None, max_length=20)
    content: str | None = Field(default=None, min_length=50, max_length=30_000)
    archived: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> ResumeUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        return self


class ResumeSummaryResponse(BaseModel):
    id: int
    name: str
    target_roles: list[str]
    content_sha256: str
    version: int
    archived: bool
    source_resume_id: int | None = None
    source_resume_version: int | None = None
    vacancy_id: str | None = None
    advice_id: int | None = None
    created_at: str
    updated_at: str


class ResumeResponse(ResumeSummaryResponse):
    content: str


class ResumeAdviceRequest(BaseModel):
    resume_id: int | None = Field(default=None, ge=1)
    resume_text: str | None = Field(default=None, min_length=50, max_length=30_000)
    language: Literal["ru", "en"] = "ru"

    @model_validator(mode="after")
    def require_one_source(self) -> ResumeAdviceRequest:
        if (self.resume_id is None) == (self.resume_text is None):
            raise ValueError("Provide exactly one of resume_id or resume_text")
        return self


class ResumeAdviceResponse(BaseModel):
    id: int
    vacancy_id: str
    profile_version: str
    resume_id: int | None = None
    resume_version: int | None = None
    resume_sha256: str
    status: Literal["draft"] = "draft"
    result: dict[str, Any]
    metadata: dict[str, Any]


class AdaptedResumeRequest(BaseModel):
    resume_id: int = Field(ge=1)
    advice_id: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/capabilities")
def capabilities(request: Request) -> dict[str, bool]:
    current = container(request)
    return {
        "llm": bool(current.settings.llm_model),
        "cover_letters": current.cover_letter_generator is not None,
        "resume_advice": current.resume_advisor is not None,
        "telegram": current.notifier is not None,
        "hh_authenticated": bool(current.settings.hh_access_token),
        "remotive": getattr(current, "remotive", None) is not None,
    }


@app.get("/app", include_in_schema=False)
def user_app() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


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


@app.post("/resumes", response_model=ResumeResponse, status_code=201)
def create_resume(payload: ResumeCreateRequest, request: Request) -> ResumeResponse:
    try:
        resume = container(request).repository.create_resume(
            payload.name, payload.target_roles, payload.content
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ResumeResponse.model_validate(resume)


@app.get("/resumes", response_model=list[ResumeSummaryResponse])
def list_resumes(
    request: Request, include_archived: bool = Query(default=False)
) -> list[ResumeSummaryResponse]:
    rows = container(request).repository.list_resumes(include_archived=include_archived)
    return [ResumeSummaryResponse.model_validate(row) for row in rows]


@app.get("/resumes/{resume_id}", response_model=ResumeResponse)
def get_resume(resume_id: int, request: Request) -> ResumeResponse:
    resume = container(request).repository.get_resume(resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return ResumeResponse.model_validate(resume)


@app.put("/resumes/{resume_id}", response_model=ResumeResponse)
def replace_resume(
    resume_id: int, payload: ResumeCreateRequest, request: Request
) -> ResumeResponse:
    try:
        resume = container(request).repository.update_resume(
            resume_id,
            name=payload.name,
            target_roles=payload.target_roles,
            content=payload.content,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return ResumeResponse.model_validate(resume)


@app.patch("/resumes/{resume_id}", response_model=ResumeResponse)
def update_resume(
    resume_id: int, payload: ResumeUpdateRequest, request: Request
) -> ResumeResponse:
    try:
        resume = container(request).repository.update_resume(
            resume_id, **payload.model_dump(exclude_unset=True)
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return ResumeResponse.model_validate(resume)


@app.get("/resumes/{resume_id}/export.docx", response_class=StreamingResponse)
def export_resume(resume_id: int, request: Request) -> StreamingResponse:
    resume = container(request).repository.get_resume(resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    filename = f"resume-{resume_id}-v{resume['version']}.docx"
    return StreamingResponse(
        iter([build_resume_docx(resume)]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/monitor/run")
async def run_monitor(request: Request, pages: int = Query(default=1, ge=1, le=10)):
    current = container(request)
    return await current.pipeline.run(current.profile_store.load(), pages=pages)


@app.get("/automation/status")
def automation_status(
    request: Request,
    x_automation_token: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    current = require_automation_token(request, x_automation_token)
    return {
        "status": "ready",
        "llm": bool(current.settings.llm_model),
        "telegram": current.notifier is not None,
        "hh_authenticated": bool(current.settings.hh_access_token),
        "remotive": getattr(current, "remotive", None) is not None,
        "profile_version": current.profile_store.load().fingerprint(),
    }


@app.post("/automation/monitor/run")
async def automation_run_monitor(
    request: Request,
    pages: int = Query(default=1, ge=1, le=10),
    x_automation_token: Annotated[str | None, Header()] = None,
):
    current = require_automation_token(request, x_automation_token)
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

    stored_resume = None
    if payload.resume_id is not None:
        stored_resume = current.repository.get_resume(payload.resume_id)
        if stored_resume is None:
            raise HTTPException(status_code=404, detail="Resume not found")
        if stored_resume["archived"]:
            raise HTTPException(status_code=409, detail="Archived resume cannot be analyzed")
        resume_text = stored_resume["content"]
        resume_hash = stored_resume["content_sha256"]
        resume_version = stored_resume["version"]
    else:
        resume_text = payload.resume_text or ""
        resume_hash = f"sha256:{sha256(resume_text.encode('utf-8')).hexdigest()}"
        resume_version = None

    profile = current.profile_store.load()
    try:
        generated = await current.resume_advisor.generate(
            vacancy, profile, resume_text, language=payload.language
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    profile_version = profile.fingerprint()
    result = generated.model_dump(
        exclude={"model", "prompt_version", "usage"}, mode="json"
    )
    metadata = {
        "model": generated.model,
        "prompt_version": generated.prompt_version,
        "usage": generated.usage,
        "language": payload.language,
        "source_resume_stored": stored_resume is not None,
    }
    advice_id = current.repository.save_resume_advice(
        vacancy_id,
        profile_version,
        resume_hash,
        result,
        metadata,
        resume_id=payload.resume_id,
        resume_version=resume_version,
    )
    return ResumeAdviceResponse(
        id=advice_id,
        vacancy_id=vacancy_id,
        profile_version=profile_version,
        resume_id=payload.resume_id,
        resume_version=resume_version,
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


@app.post(
    "/vacancies/{vacancy_id}/adapted-resume",
    response_model=ResumeResponse,
    status_code=201,
)
def create_adapted_resume(
    vacancy_id: str, payload: AdaptedResumeRequest, request: Request
) -> ResumeResponse:
    current = container(request)
    vacancy = current.repository.get_vacancy(vacancy_id)
    source = current.repository.get_resume(payload.resume_id)
    advice = current.repository.get_resume_advice(payload.advice_id)
    if vacancy is None:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    if source is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    if advice is None:
        raise HTTPException(status_code=404, detail="Resume advice not found")
    if advice["vacancy_id"] != vacancy_id or advice["resume_id"] != payload.resume_id:
        raise HTTPException(status_code=409, detail="Advice does not match vacancy and resume")
    if (
        advice["resume_version"] != source["version"]
        or advice["resume_sha256"] != source["content_sha256"]
    ):
        raise HTTPException(status_code=409, detail="Source resume changed after advice")

    name = (payload.name or f"{source['name']} — {vacancy.name}")[:120].rstrip()
    try:
        copied = current.repository.create_resume(
            name,
            [vacancy.name],
            source["content"],
            source_resume_id=source["id"],
            source_resume_version=source["version"],
            vacancy_id=vacancy_id,
            advice_id=payload.advice_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ResumeResponse.model_validate(copied)


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
    message = payload.get("message")
    if message:
        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id != str(current.settings.telegram_chat_id):
            return {"ok": True}
        telegram_bot = getattr(current, "telegram_bot", None)
        if telegram_bot is not None:
            await telegram_bot.handle_message(message)
        return {"ok": True}
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
