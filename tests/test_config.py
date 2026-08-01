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


def test_load_app_config_rejects_download_missing_until_implemented(tmp_path: Path) -> None:
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

    with pytest.raises(ConfigError, match="download_missing=true is not implemented yet"):
        load_app_config(config_path)


def test_load_runtime_config_requires_env_credentials() -> None:
    with pytest.raises(ConfigError, match="SPOTIFY_CLIENT_ID"):
        load_runtime_config({})


def test_load_runtime_config_rejects_dry_run_until_implemented() -> None:
    env = {
        "SPOTIFY_CLIENT_ID": "client-id",
        "SPOTIFY_CLIENT_SECRET": "client-secret",
        "NAVIDROME_URL": "https://navidrome.example.org",
        "NAVIDROME_USERNAME": "user",
        "NAVIDROME_PASSWORD": "password",
        "DRY_RUN": "true",
    }

    with pytest.raises(ConfigError, match="DRY_RUN=true is not implemented yet"):
        load_runtime_config(env)
