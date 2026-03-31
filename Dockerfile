FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PST_AGENT_DATA_DIR=/app/state \
    PST_AGENT_TEMP_DIR=/app/state/tmp \
    PST_AGENT_ATTACHMENTS_DIR=/app/state/attachments \
    PST_AGENT_DB_PATH=/app/state/index.sqlite3 \
    PST_AGENT_HOST=0.0.0.0 \
    PST_AGENT_PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        ca-certificates \
        gcc \
        libmagic1 \
        pst-utils \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts

RUN pip install -e . \
    && chmod +x /app/scripts/run-container.sh \
    && mkdir -p /app/state /data/inbox

EXPOSE 8000

ENTRYPOINT ["/app/scripts/run-container.sh"]
CMD ["api"]
