# ScholarMind public web image.
# Builds the React frontend and runs Nginx + FastAPI + worker in one container.

FROM node:20-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi

COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    DATABASE_URL=sqlite:////app/data/scholarmind.db \
    PDF_STORAGE_ROOT=/app/data/papers \
    CORS_ALLOW_ORIGINS=*

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gettext-base \
    nginx \
    sqlite3 \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md alembic.ini ./
COPY apps/ apps/
COPY packages/ packages/
COPY scripts/ scripts/
COPY infra/ infra/

RUN pip install --no-cache-dir ".[llm,pdf]" \
    && pip install --no-cache-dir psutil umap-learn

COPY --from=frontend-builder /build/frontend/dist /usr/share/nginx/html

RUN mkdir -p /app/data/papers /app/logs /run/nginx \
    && rm -f /etc/nginx/sites-enabled/default \
    && chmod +x /app/scripts/start_web_container.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD-SHELL curl -sf "http://127.0.0.1:${PORT:-8080}/health" || exit 1

CMD ["sh", "/app/scripts/start_web_container.sh"]
