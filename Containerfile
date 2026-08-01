# syntax=docker/dockerfile:1.26.0

FROM ghcr.io/astral-sh/uv:0.12.1@sha256:cf4eedcaa81655197f625739489effcbe71b61ceb1506f332c3facae5deceded AS uv

FROM python:3.14-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30

LABEL org.opencontainers.image.title="spotify-navidrome-sync"
LABEL org.opencontainers.image.description="One-shot Spotify playlist to Navidrome playlist sync job"

ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /usr/local/bin/

RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid 1000 --home-dir /tmp --shell /usr/sbin/nologin app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable \
    && rm -rf /usr/local/lib/python3.12/site-packages/pip \
        /usr/local/lib/python3.12/site-packages/pip-*.dist-info \
        /usr/local/bin/pip \
        /usr/local/bin/pip3 \
        /usr/local/bin/pip3.12 \
        /tmp/.cache/uv \
    && chown -R app:app /app /tmp

HEALTHCHECK NONE

USER 1000:1000

ENTRYPOINT ["/app/.venv/bin/spotify-navidrome-sync"]
