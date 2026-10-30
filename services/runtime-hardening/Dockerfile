# runtime-hardening — local development image.
# Build context is the repository ROOT (docker compose sets context: ".").
# Runtime dependencies are installed into /app/.venv so that docker compose's
# anonymous /app/.venv volume is seeded; the worker source itself is
# bind-mounted from the host by docker-compose. The service mounts /var/run/
# docker.sock and is privileged because it manages agent containers/cgroups.
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

# Runtime dependencies declared in services/runtime-hardening/pyproject.toml.
RUN /app/.venv/bin/pip install \
    "pydantic>=2.7" \
    "pydantic-settings>=2.3" \
    "pyyaml>=6.0" \
    "fastapi>=0.111" \
    "uvicorn>=0.30" \
    "prometheus-client>=0.20"

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8002
CMD ["uvicorn", "runtime.main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"]