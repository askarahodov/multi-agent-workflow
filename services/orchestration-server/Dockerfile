# orchestration-server — local development image.
# Build context is the repository ROOT (docker compose sets context: ".").
# Runtime dependencies are installed into /app/.venv so that docker compose's
# anonymous /app/.venv volume is seeded; the worker source itself is
# bind-mounted from the host by docker-compose.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Local `shared` package (dependencies reference it by absolute path).
COPY packages/shared /tmp/shared
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install --upgrade pip \
    && /app/.venv/bin/pip install /tmp/shared \
    && rm -rf /tmp/shared

# Runtime dependencies declared in services/orchestration-server/pyproject.toml.
RUN /app/.venv/bin/pip install \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "sqlalchemy[asyncio]>=2.0" \
    "pydantic>=2.7" \
    "aiosqlite>=0.20" \
    "jsonschema>=4.20" \
    "httpx>=0.27"

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000
CMD ["uvicorn", "orchestration_server.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]