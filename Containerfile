# syntax=docker/dockerfile:1.27.0@sha256:bde3983e9c939224420ddaf6b784cc30e09b035a4dea01f581230c50809f372e

FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv

FROM python:3.14-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d

LABEL org.opencontainers.image.title="spotify-navidrome-sync"
LABEL org.opencontainers.image.description="One-shot Spotify playlist to Navidrome playlist sync job"

ENV HOME=/tmp \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid 1000 --home-dir /tmp --shell /usr/sbin/nologin app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable \
    && rm -rf /usr/local/lib/python*/site-packages/pip \
        /usr/local/lib/python*/site-packages/pip-*.dist-info \
        /usr/local/bin/pip* \
        /tmp/.cache/uv \
    && chown -R app:app /app /tmp

HEALTHCHECK NONE

USER 1000:1000

ENTRYPOINT ["/app/.venv/bin/spotify-navidrome-sync"]
