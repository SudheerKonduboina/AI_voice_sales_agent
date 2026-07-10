# Multi-stage Dockerfile for AI Voice Sales Agent

# --- Dashboard build stage ---
FROM node:20-alpine AS dashboard-build
WORKDIR /app/dashboard
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm install
COPY dashboard/ ./
RUN npm run build

# --- Python application stage ---
FROM python:3.12-slim AS app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-optional.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user for security
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -m -s /bin/bash appuser

COPY agent/ ./agent/
COPY crm/ ./crm/
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY --from=dashboard-build /app/dashboard/dist ./dashboard/dist

RUN mkdir -p logs logs/analytics models && \
    chown -R appuser:appuser /app

USER appuser

ENV PYTHONPATH=/app/agent:/app/crm
ENV CONFIG_PATH=/app/config/config.yaml

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "agent"]
