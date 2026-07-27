FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip pip install .
COPY config ./config
RUN mkdir -p /app/data

FROM base AS test
RUN --mount=type=cache,target=/root/.cache/pip pip install "pytest>=8.3,<9"
COPY tests ./tests
CMD ["pytest", "-q"]

FROM base AS lint
RUN --mount=type=cache,target=/root/.cache/pip pip install "ruff==0.16.0"
COPY tests ./tests
CMD ["ruff", "check", "."]

FROM base AS runtime
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["uvicorn", "job_copilot.api:app", "--host", "0.0.0.0", "--port", "8000"]
