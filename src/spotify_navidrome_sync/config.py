from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when runtime configuration is invalid."""


@dataclass(frozen=True)
class SourceConfig:
    spotify_playlist_id: str
    navidrome_playlist_name: str
    download_missing: bool = False


@dataclass(frozen=True)
class AppConfig:
    sources: tuple[SourceConfig, ...]


@dataclass(frozen=True)
class RuntimeConfig:
    spotify_client_id: str
    spotify_client_secret: str
    navidrome_url: str
    navidrome_username: str
    navidrome_password: str
    log_level: str = "INFO"


def load_app_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"failed to read config file {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"failed to parse config file {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("config file must contain a mapping")

    sources_raw = raw.get("sources")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise ConfigError("config must contain a non-empty sources list")

    sources: list[SourceConfig] = []
    for index, source_raw in enumerate(sources_raw, start=1):
        if not isinstance(source_raw, dict):
            raise ConfigError(f"source {index} must be a mapping")
        sources.append(_parse_source(index, source_raw))

    return AppConfig(sources=tuple(sources))


def load_runtime_config(env: Mapping[str, str]) -> RuntimeConfig:
    required = {
        "SPOTIFY_CLIENT_ID": "spotify_client_id",
        "SPOTIFY_CLIENT_SECRET": "spotify_client_secret",
        "NAVIDROME_URL": "navidrome_url",
        "NAVIDROME_USERNAME": "navidrome_username",
        "NAVIDROME_PASSWORD": "navidrome_password",
    }
    values: dict[str, str] = {}
    missing: list[str] = []

    for env_name, field_name in required.items():
        value = env.get(env_name, "").strip()
        if not value:
            missing.append(env_name)
        else:
            values[field_name] = value

    if missing:
        raise ConfigError(f"missing required environment variables: {', '.join(missing)}")

    if _env_true(env.get("DRY_RUN")):
        raise ConfigError("DRY_RUN=true is not implemented yet")

    return RuntimeConfig(
        spotify_client_id=values["spotify_client_id"],
        spotify_client_secret=values["spotify_client_secret"],
        navidrome_url=values["navidrome_url"],
        navidrome_username=values["navidrome_username"],
        navidrome_password=values["navidrome_password"],
        log_level=env.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
    )


def _parse_source(index: int, source_raw: Mapping[str, Any]) -> SourceConfig:
    playlist_id = _required_string(index, source_raw, "spotify_playlist_id")
    playlist_name = _required_string(index, source_raw, "navidrome_playlist_name")
    download_missing = _optional_bool(source_raw.get("download_missing", False))

    if download_missing:
        raise ConfigError(f"source {index} download_missing=true is not implemented yet")

    return SourceConfig(
        spotify_playlist_id=playlist_id,
        navidrome_playlist_name=playlist_name,
        download_missing=download_missing,
    )


def _required_string(index: int, source_raw: Mapping[str, Any], key: str) -> str:
    value = source_raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"source {index} missing required field: {key}")
    return value.strip()


def _optional_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ConfigError("download_missing must be a boolean")


def _env_true(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}
