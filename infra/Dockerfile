FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --create-home --uid 1000 app
COPY pyproject.toml ./
COPY src ./src

FROM base AS dev
RUN pip install -e ".[dev,ml,sim,report]"
COPY tests ./tests
CMD ["pytest", "-q"]

FROM base AS app
RUN pip install ".[ml,sim]" \
    && mkdir -p /data/artifacts/logs \
    && chown -R app:app /data
ENV APP_ENV=cloud LOG_URI=/data/artifacts/logs/actions.jsonl
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "src.agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
