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
    download_target: str | None = None
    cleanup_downloads: bool = False


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
    download_root: Path = Path("/media")
    spotdl_bin: str = "spotdl"
    navidrome_scan_timeout_seconds: int = 900


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
        download_root=Path(env.get("DOWNLOAD_ROOT", "/media").strip() or "/media"),
        spotdl_bin=env.get("SPOTDL_BIN", "spotdl").strip() or "spotdl",
        navidrome_scan_timeout_seconds=_optional_positive_int(
            env.get("NAVIDROME_SCAN_TIMEOUT_SECONDS"),
            default=900,
            name="NAVIDROME_SCAN_TIMEOUT_SECONDS",
        ),
    )


def _parse_source(index: int, source_raw: Mapping[str, Any]) -> SourceConfig:
    playlist_id = _required_string(index, source_raw, "spotify_playlist_id")
    playlist_name = _required_string(index, source_raw, "navidrome_playlist_name")
    download_missing = _optional_bool(source_raw.get("download_missing", False))
    cleanup_downloads = _optional_bool(source_raw.get("cleanup_downloads", False))
    download_target = _optional_string(source_raw.get("download_target"))

    if download_missing:
        if download_target is None:
            raise ConfigError(
                f"source {index} download_target is required when download_missing=true"
            )
        _validate_download_target(index, download_target)
    elif download_target is not None:
        _validate_download_target(index, download_target)

    if cleanup_downloads and download_target is None:
        raise ConfigError(f"source {index} download_target is required when cleanup_downloads=true")

    return SourceConfig(
        spotify_playlist_id=playlist_id,
        navidrome_playlist_name=playlist_name,
        download_missing=download_missing,
        download_target=download_target,
        cleanup_downloads=cleanup_downloads,
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
    raise ConfigError("boolean config values must be true or false")


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("optional string config values must be non-empty strings")
    return value.strip()


def _validate_download_target(index: int, value: str) -> None:
    path = Path(value)
    if path.is_absolute() or path.name != value or value in {".", ".."}:
        raise ConfigError(f"source {index} download_target must be a safe single path segment")
    if ".." in path.parts or "/" in value or "\\" in value:
        raise ConfigError(f"source {index} download_target must be a safe single path segment")


def _optional_positive_int(value: str | None, *, default: int, name: str) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return parsed


def _env_true(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}
