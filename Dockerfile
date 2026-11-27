# The TeleCompass API, for Cloud Run. It serves the rules engine; it never calls a model.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependencies first, so they are cached when only the code changes.
COPY pyproject.toml uv.lock README.md ./
COPY telecompass/__init__.py telecompass/__init__.py
RUN uv sync --frozen --no-dev

COPY telecompass ./telecompass
RUN uv sync --frozen --no-dev

# Cloud Run tells the container which port to listen on.
ENV PORT=8080
CMD ["sh", "-c", "exec uv run --no-sync uvicorn telecompass.api:production_app --factory --host 0.0.0.0 --port ${PORT}"]
