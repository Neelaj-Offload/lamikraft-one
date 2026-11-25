# Lamikraft One backend: the FastAPI API and the polling worker share this image.
# Railway runs two services from it; LK_PROCESS picks the process (see start.sh and docs/runbooks/hosting.md).
FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# fonts and libraries the PDF engine and image handling need at runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g libfreetype6 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY start.sh ./start.sh
RUN chmod +x ./start.sh && useradd --create-home --uid 10001 lamikraft && chown -R lamikraft /app
USER lamikraft

ENV LK_ENV=production PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["./start.sh"]
