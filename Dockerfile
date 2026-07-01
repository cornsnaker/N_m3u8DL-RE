# N_m3u8DL-RE Telegram Bot runtime image (multi-stage).
# Bundles N_m3u8DL-RE, ffmpeg, mp4decrypt (Bento4), mkvmerge and
# Shaka Packager so the bot is self-contained for downloading,
# decrypting and muxing HLS/DASH/MSS streams.

# ---- Builder: compile Python wheels ----
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt ./
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---- Downloader: fetch N_m3u8DL-RE + Bento4 mp4decrypt ----
FROM debian:bookworm-slim AS downloader

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates unzip \
    && rm -rf /var/lib/apt/lists/*

ARG N_M3U8DL_RE_VERSION=v0.3.0-beta
ARG TARGETARCH=amd64

# Download N_m3u8DL-RE (self-contained .NET AOT binary).
RUN set -eux; \
    if [ "$TARGETARCH" = "arm64" ]; then \
        ARCH="linux-arm64"; \
    else \
        ARCH="linux-x64"; \
    fi; \
    curl -fSL "https://github.com/nilaoda/N_m3u8DL-RE/releases/download/${N_M3U8DL_RE_VERSION}/N_m3u8DL-RE_Beta_${ARCH}" \
         -o /usr/local/bin/N_m3u8DL-RE \
    && chmod +x /usr/local/bin/N_m3u8DL-RE

# Download Bento4 mp4decrypt.
ARG BENTO4_VERSION=1-6-0-641
RUN set -eux; \
    if [ "$TARGETARCH" = "arm64" ]; then \
        BENTO4_ARCH="aarch64-unknown-linux-gnu"; \
    else \
        BENTO4_ARCH="x86_64-unknown-linux"; \
    fi; \
    curl -fSL "https://www.bok.net/Bento4/binaries/Bento4-SDK-${BENTO4_VERSION}.${BENTO4_ARCH}.zip" \
         -o /tmp/bento4.zip \
    && unzip -j /tmp/bento4.zip "*/bin/mp4decrypt" -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/mp4decrypt \
    && rm /tmp/bento4.zip

# ---- Runtime ----
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    WORK_DIR=/data

# System dependencies: ffmpeg (muxing/decryption), mkvmerge (MKV muxing).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        mkvtoolnix \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install pre-built Python wheels.
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Copy binaries from downloader stage.
COPY --from=downloader /usr/local/bin/N_m3u8DL-RE /usr/local/bin/N_m3u8DL-RE
COPY --from=downloader /usr/local/bin/mp4decrypt /usr/local/bin/mp4decrypt

# Application code.
COPY m3u8bot ./m3u8bot

# Persistent working directory for downloads and session file.
RUN mkdir -p /data
VOLUME ["/data"]

# Config via env vars or --env-file.
# Required: TELEGRAM_API_ID, TELEGRAM_API_HASH, BOT_TOKEN
ENTRYPOINT ["python", "-m", "m3u8bot"]
