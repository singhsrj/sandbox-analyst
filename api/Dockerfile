# SandboxAnalyst API image. Build from the repository root:
#   docker build -f api/Dockerfile -t sandbox-analyst-api .
#
# - dependencies come from the committed uv.lock (--frozen): the image runs exactly what was tested
# - no secrets in the image: everything is read from the environment at runtime (deploy/.env)
# - runs as an unprivileged user; /app/runs (artifacts) is the only writable path, mounted as a volume

FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# dependency layer first (cached until the lock file changes)
COPY pyproject.toml uv.lock ./
COPY api/pyproject.toml api/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-workspace --package sandbox-analyst-api
COPY api/app api/app
RUN uv sync --frozen --no-dev --package sandbox-analyst-api

FROM python:3.12-slim-bookworm
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app
COPY --from=build --chown=app:app /app /app
RUN mkdir -p /app/runs && chown app:app /app/runs
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 APP_ENV=prod
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["python", "-m", "app.serve", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
