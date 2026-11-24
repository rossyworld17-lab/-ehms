# ---- build the web client (exact versions from package-lock.json)
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- runtime: unprivileged user, no compilers, read-only friendly
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    EHMS_FRONTEND_DIST=/app/frontend/dist EHMS_ENV=production \
    EHMS_DATA_DIR=/data EHMS_DOCUMENT_DIR=/data/documents EHMS_BACKUP_DIR=/data/backups
WORKDIR /app/backend
RUN useradd --create-home --uid 10001 ehms && mkdir -p /data/documents /data/backups && chown -R ehms /data
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
USER ehms
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
# Trust X-Forwarded-For only from the reverse proxy network (docker-compose sets it); never "*".
ENV FORWARDED_ALLOW_IPS=127.0.0.1 WEB_CONCURRENCY=2
CMD ["sh", "-c", "exec uvicorn ehms.app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\" --workers \"$WEB_CONCURRENCY\" --no-server-header --timeout-graceful-shutdown 20"]
