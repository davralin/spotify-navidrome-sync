# syntax=docker/dockerfile:1.26.0@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32

FROM ghcr.io/astral-sh/uv:0.12.2@sha256:069a51314a7bb6031777a9273205fe1b0b19e914ef418207d1338b268df641dd AS uv

FROM python:3.14-slim@sha256:7bec7ddcddeff7975d6ba9b4be7dd6f6b2f55e7491539145e2978f7f97ce9144

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
