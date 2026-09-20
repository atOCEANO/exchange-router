FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir ".[server]"


FROM base AS test

RUN pip install --no-cache-dir ".[test,audit]"

CMD ["pytest", "-q"]


FROM base AS service

RUN useradd --create-home --uid 1000 appuser && chown -R appuser /app
USER appuser

CMD ["uvicorn", "exchange_router.service:app", "--host", "0.0.0.0", "--port", "8040", "--ws-ping-interval", "30", "--ws-ping-timeout", "60"]
