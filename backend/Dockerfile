# Backend: FastAPI app + bundled agent_os library
# Build context = repo root (so agent_os/ is available)
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install agent_os library first (changes less often)
COPY pyproject.toml ./
COPY agent_os ./agent_os
RUN pip install --upgrade pip && pip install -e .

# Install backend deps
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Copy backend source
COPY backend ./backend

WORKDIR /app/backend

EXPOSE 8080

# Cloud Run injects $PORT — bind to it
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
