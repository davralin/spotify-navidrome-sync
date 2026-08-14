from __future__ import annotations

from pathlib import Path

import pytest

from spotify_navidrome_sync.config import ConfigError, load_app_config, load_runtime_config


def test_load_app_config_ignores_unknown_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
spotify_client_secret: ignored
sources:
  - spotify_playlist_id: "4Llq96RL2xSSl1U8LaFxCm"
    navidrome_playlist_name: "Spotify Sync Test - 90s"
    random_future_value: ignored
""",
        encoding="utf-8",
    )

    config = load_app_config(config_path)

    assert len(config.sources) == 1
    assert config.sources[0].spotify_playlist_id == "4Llq96RL2xSSl1U8LaFxCm"
    assert config.sources[0].navidrome_playlist_name == "Spotify Sync Test - 90s"
    assert config.sources[0].download_missing is False


def test_load_app_config_requires_playlist_id(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sources:
  - navidrome_playlist_name: "Spotify Sync Test"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="source 1 missing required field: spotify_playlist_id"):
        load_app_config(config_path)


def test_load_app_config_accepts_download_policy(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sources:
  - spotify_playlist_id: "4Llq96RL2xSSl1U8LaFxCm"
    navidrome_playlist_name: "Spotify Sync Test"
    download_missing: true
    download_target: "90s"
    cleanup_downloads: true
""",
        encoding="utf-8",
    )

    config = load_app_config(config_path)

    assert config.sources[0].download_missing is True
    assert config.sources[0].download_target == "90s"
    assert config.sources[0].cleanup_downloads is True


@pytest.mark.parametrize("target", ["../90s", "rip/90s", "/media/90s", "..", "."])
def test_load_app_config_rejects_unsafe_download_target(tmp_path: Path, target: str) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
sources:
  - spotify_playlist_id: "4Llq96RL2xSSl1U8LaFxCm"
    navidrome_playlist_name: "Spotify Sync Test"
    download_missing: true
    download_target: "{target}"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="download_target must be a safe single path segment"):
        load_app_config(config_path)


def test_load_app_config_requires_download_target_for_downloads(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sources:
  - spotify_playlist_id: "4Llq96RL2xSSl1U8LaFxCm"
    navidrome_playlist_name: "Spotify Sync Test"
    download_missing: true
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="download_target is required"):
        load_app_config(config_path)


def test_load_runtime_config_requires_env_credentials() -> None:
    with pytest.raises(ConfigError, match="SPOTIFY_CLIENT_ID"):
        load_runtime_config({})


def test_load_runtime_config_accepts_dry_run() -> None:
    env = {
        "SPOTIFY_CLIENT_ID": "client-id",
        "SPOTIFY_CLIENT_SECRET": "client-secret",
        "NAVIDROME_URL": "https://navidrome.example.org",
        "NAVIDROME_USERNAME": "user",
        "NAVIDROME_PASSWORD": "password",
        "DRY_RUN": "true",
    }

    runtime = load_runtime_config(env)

    assert runtime.dry_run is True


def test_load_runtime_config_accepts_downloader_runtime_env() -> None:
    env = {
        "SPOTIFY_CLIENT_ID": "client-id",
        "SPOTIFY_CLIENT_SECRET": "client-secret",
        "NAVIDROME_URL": "https://navidrome.example.org",
        "NAVIDROME_USERNAME": "user",
        "NAVIDROME_PASSWORD": "password",
        "DOWNLOAD_ROOT": "/scratch/media",
        "SPOTDL_BIN": "/usr/local/bin/spotdl",
        "NAVIDROME_SCAN_TIMEOUT_SECONDS": "123",
    }

    runtime = load_runtime_config(env)

    assert runtime.download_root == Path("/scratch/media")
    assert runtime.spotdl_bin == "/usr/local/bin/spotdl"
    assert runtime.navidrome_scan_timeout_seconds == 123
