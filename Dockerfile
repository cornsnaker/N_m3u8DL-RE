# N_m3u8DL-RE Telegram Bot runtime image (multi-stage).

# ---- Builder: compile wheels (tgcrypto needs a C toolchain) ----
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt ./
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---- Runtime ----
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    WORK_DIR=/data

# System deps: ffmpeg (for muxing) and the N_m3u8DL-RE binary.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        wget \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# Download N_m3u8DL-RE Linux binary.
ARG N_M3U8DL_VERSION=v0.3.1-beta
RUN wget -q "https://github.com/nilaoda/N_m3u8DL-RE/releases/download/${N_M3U8DL_VERSION}/N_m3u8DL-RE_${N_M3U8DL_VERSION}_linux-x64.tar.gz" \
        -O /tmp/n_m3u8dl.tar.gz \
    && mkdir -p /tmp/n_m3u8dl \
    && tar -xzf /tmp/n_m3u8dl.tar.gz -C /tmp/n_m3u8dl \
    && find /tmp/n_m3u8dl -name "N_m3u8DL-RE" -exec cp {} /usr/local/bin/N_m3u8DL-RE \; \
    && chmod +x /usr/local/bin/N_m3u8DL-RE \
    && rm -rf /tmp/n_m3u8dl /tmp/n_m3u8dl.tar.gz

WORKDIR /app

# Install pre-built wheels.
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Application code.
COPY n_m3u8dl_bot ./n_m3u8dl_bot

# Persistent working directory for downloads / session file.
RUN mkdir -p /data
VOLUME ["/data"]

# Config is supplied at runtime via env vars or an --env-file.
# Required: TELEGRAM_API_ID, TELEGRAM_API_HASH, BOT_TOKEN
ENTRYPOINT ["python", "-m", "n_m3u8dl_bot"]
