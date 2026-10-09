# syntax=docker/dockerfile:1.7
# ApprovalReady API / worker / scheduler image (same image, different commands).

ARG PYTHON_VERSION=3.14

FROM python:${PYTHON_VERSION}-slim AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
# Optional BuildKit secret "extra_ca" lets builds run behind a TLS-intercepting proxy:
#   docker build --secret id=extra_ca,src=/path/ca.pem ...
RUN --mount=type=secret,id=extra_ca,required=false \
    --mount=type=cache,target=/root/.cache/uv \
    if [ -s /run/secrets/extra_ca ]; then \
      export SSL_CERT_FILE=/run/secrets/extra_ca PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-cache-dir "uv>=0.8,<0.9" \
    && uv sync --frozen --no-dev --no-install-project

FROM python:${PYTHON_VERSION}-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"
# Pango and fonts for PDF reports (WeasyPrint). /data/uploads is the local document store
# (a volume in Compose); creating it here gives the volume the app user's ownership.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /data/uploads && chown app:app /data/uploads && chmod 700 /data/uploads
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app docker/ ./docker/
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).status == 200 else 1)"]
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["api"]
