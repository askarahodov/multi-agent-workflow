# agent-management — local development image.
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
COPY shared /tmp/shared
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install --upgrade pip \
    && /app/.venv/bin/pip install /tmp/shared \
    && rm -rf /tmp/shared

# Runtime dependencies declared in agent-management/pyproject.toml, plus
# `cryptography` which the code imports (agent_management/crypto.py) but which
# pyproject.toml does not list.
RUN /app/.venv/bin/pip install \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "sqlalchemy[asyncio]>=2.0" \
    "pydantic>=2.7" \
    "aiosqlite>=0.20" \
    "httpx>=0.27" \
    "cryptography>=42"

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8001
CMD ["uvicorn", "agent_management.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]