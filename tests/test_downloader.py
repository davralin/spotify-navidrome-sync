from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from spotify_navidrome_sync.downloader import OUTPUT_TEMPLATE, SpotdlDownloader
from spotify_navidrome_sync.spotify import SpotifyTrack


def test_spotdl_command_downloads_explicit_track_urls_without_sync_or_m3u(tmp_path: Path) -> None:
    track = SpotifyTrack(
        name="Song",
        artists=("Artist",),
        duration_seconds=120,
        isrc="NO1234567890",
        spotify_id="spotify-track-id",
    )
    downloader = SpotdlDownloader(
        binary="spotdl",
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
    )

    command = downloader.build_command((track,), target_dir=tmp_path)

    assert command[0] == "spotdl"
    assert "download" in command
    assert "sync" not in command
    assert "--m3u" not in command
    assert "--max-filename-length" not in command
    assert "https://open.spotify.com/track/spotify-track-id" in command
    assert str(tmp_path / OUTPUT_TEMPLATE) in command
    assert command[command.index("--format") + 1] == "mp3"


def test_download_missing_records_only_files_spotdl_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = SpotifyTrack(
        name="Created Song",
        artists=("Artist",),
        duration_seconds=120,
        isrc="NO1234567890",
        spotify_id="created-track-id",
    )
    skipped = SpotifyTrack(
        name="Skipped Song",
        artists=("Artist",),
        duration_seconds=120,
        isrc="NO1234567891",
        spotify_id="skipped-track-id",
    )
    (tmp_path / "Artist_-_Created Song_-_created-track-id.mp3").write_text(
        "audio",
        encoding="utf-8",
    )
    downloader = SpotdlDownloader(
        binary="spotdl",
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
    )

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=args, returncode=0, stdout=""),
    )

    entries = downloader.download_missing((created, skipped), target_dir=tmp_path)

    assert tuple(entry.spotify_id for entry in entries) == ("created-track-id",)


def test_download_missing_still_recognizes_prefix_id_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    track = SpotifyTrack(
        name="Created Song",
        artists=("Artist",),
        duration_seconds=120,
        isrc="NO1234567890",
        spotify_id="created-track-id",
    )
    (tmp_path / "created-track-id_-_Artist_-_Created Song.mp3").write_text(
        "audio",
        encoding="utf-8",
    )
    downloader = SpotdlDownloader(
        binary="spotdl",
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
    )

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=args, returncode=0, stdout=""),
    )

    entries = downloader.download_missing((track,), target_dir=tmp_path)

    assert tuple(entry.spotify_id for entry in entries) == ("created-track-id",)
