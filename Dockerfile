# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS dependencies
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=0
WORKDIR /build
COPY backend/requirements.txt ./requirements.txt
RUN python -m venv /opt/venv
RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install --no-warn-script-location -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DATA_DIR=/app/data \
    PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY backend/app /app/app
COPY data /app/data
RUN chgrp -R 0 /app \
    && chmod -R g=u /app
USER 10001:0
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=45s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/api/health/live', timeout=2).read()" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
