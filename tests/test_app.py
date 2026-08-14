from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest

from spotify_navidrome_sync.app import RunReport, _print_report, _sync_playlist
from spotify_navidrome_sync.config import RuntimeConfig, SourceConfig
from spotify_navidrome_sync.downloader import SpotdlDownloader
from spotify_navidrome_sync.manifest import ManifestEntry, load_manifest, write_manifest
from spotify_navidrome_sync.navidrome import NavidromeClient, NavidromePlaylist, NavidromeSong
from spotify_navidrome_sync.spotify import SpotifyPlaylist, SpotifyTrack


class FakeNavidrome:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.scan_started = False
        self.replaced_song_ids: tuple[str, ...] = ()

    def search_songs(self, query: str, *, count: int = 10) -> tuple[NavidromeSong, ...]:
        self.events.append(f"search:{query}")
        if not self.scan_started:
            return ()
        return (
            NavidromeSong(
                "navidrome-song",
                "Song",
                "Artist",
                120,
                "mp3",
                ("NO1234567890",),
                {"path": "small-test/Artist_-_Song_-_spotify-track.mp3"},
            ),
        )

    def start_scan(self) -> None:
        self.events.append("start_scan")
        self.scan_started = True

    def wait_for_scan_completion(self, *, timeout_seconds: int, poll_seconds: float = 5.0) -> None:
        self.events.append(f"wait_scan:{timeout_seconds}")

    def replace_playlist(self, name: str, song_ids: tuple[str, ...]) -> str:
        self.events.append(f"replace:{name}")
        self.replaced_song_ids = song_ids
        return "playlist-id"

    def get_playlists(self) -> tuple[NavidromePlaylist, ...]:
        return ()


class FakeDownloader(SpotdlDownloader):
    def __init__(self) -> None:
        super().__init__(
            binary="spotdl",
            spotify_client_id="client-id",
            spotify_client_secret="client-secret",
        )
        self.downloaded: list[str] = []

    def download_missing(
        self,
        tracks: Sequence[SpotifyTrack],
        *,
        target_dir: Path,
    ) -> tuple[ManifestEntry, ...]:
        self.downloaded.extend(track.spotify_id or "" for track in tracks)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / "Artist_-_Song_-_spotify-track.mp3"
        path.write_text("downloaded", encoding="utf-8")
        return (
            ManifestEntry(
                "spotify-track",
                "NO1234567890",
                "Artist",
                "Song",
                path,
            ),
        )


def test_sync_playlist_downloads_scans_rematches_then_replaces_playlist(tmp_path: Path) -> None:
    navidrome = FakeNavidrome()
    downloader = FakeDownloader()
    playlist = SpotifyPlaylist(
        spotify_id="playlist-id",
        name="Small",
        total_tracks=1,
        tracks=(
            SpotifyTrack(
                "Song",
                ("Artist",),
                120,
                "NO1234567890",
                "spotify-track",
            ),
        ),
    )
    source = SourceConfig(
        spotify_playlist_id="playlist-id",
        navidrome_playlist_name="Small Downloader Test",
        download_missing=True,
        download_target="small-test",
        cleanup_downloads=True,
    )
    runtime = RuntimeConfig(
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
        navidrome_url="https://navidrome.example.org",
        navidrome_username="user",
        navidrome_password="password",
        download_root=tmp_path,
        navidrome_scan_timeout_seconds=7,
    )
    target = tmp_path / "small-test"
    target.mkdir()
    stale_path = target / "Stale_-_Song_-_stale-track.mp3"
    stale_path.write_text("stale", encoding="utf-8")
    write_manifest(
        target,
        (
            ManifestEntry(
                "stale-track",
                None,
                "Stale",
                "Song",
                stale_path,
            ),
        ),
    )

    report = _sync_playlist(
        cast(NavidromeClient, navidrome),
        downloader,
        playlist,
        source,
        runtime,
    )

    assert downloader.downloaded == ["spotify-track"]
    assert navidrome.replaced_song_ids == ("navidrome-song",)
    assert navidrome.events == [
        "search:Artist Song",
        "start_scan",
        "wait_scan:7",
        "search:Artist Song",
        "replace:Small Downloader Test",
        "start_scan",
        "wait_scan:7",
    ]
    assert [entry.spotify_id for entry in load_manifest(target)] == ["spotify-track"]
    assert (target / "Artist_-_Song_-_spotify-track.mp3").exists()
    assert not stale_path.exists()
    assert report.action == "updated"
    assert report.navidrome_playlist_id == "playlist-id"
    assert report.matched == 1
    assert report.downloaded == 1
    assert report.cleaned_up == 1


def test_sync_playlist_matches_downloaded_manifest_file_by_relative_path(tmp_path: Path) -> None:
    class ManifestPathNavidrome(FakeNavidrome):
        def search_songs(self, query: str, *, count: int = 10) -> tuple[NavidromeSong, ...]:
            self.events.append(f"search:{query}")
            if not self.scan_started:
                return ()
            return (
                NavidromeSong(
                    "navidrome-song",
                    "Different title from indexed tags",
                    "Different artist",
                    999,
                    "mp3",
                    (),
                    {"path": "small-test/Artist_-_Song_-_spotify-track.mp3"},
                ),
            )

    navidrome = ManifestPathNavidrome()
    downloader = FakeDownloader()
    playlist = SpotifyPlaylist(
        spotify_id="playlist-id",
        name="Small",
        total_tracks=1,
        tracks=(
            SpotifyTrack(
                "Song",
                ("Artist",),
                120,
                "NO1234567890",
                "spotify-track",
            ),
        ),
    )
    source = SourceConfig(
        spotify_playlist_id="playlist-id",
        navidrome_playlist_name="Small Downloader Test",
        download_missing=True,
        download_target="small-test",
    )
    runtime = RuntimeConfig(
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
        navidrome_url="https://navidrome.example.org",
        navidrome_username="user",
        navidrome_password="password",
        download_root=tmp_path,
        navidrome_scan_timeout_seconds=7,
    )

    _sync_playlist(
        cast(NavidromeClient, navidrome),
        downloader,
        playlist,
        source,
        runtime,
    )

    assert downloader.downloaded == ["spotify-track"]
    assert navidrome.replaced_song_ids == ("navidrome-song",)


def test_sync_playlist_dry_run_plans_without_mutating(tmp_path: Path) -> None:
    navidrome = FakeNavidrome()
    downloader = FakeDownloader()
    playlist = SpotifyPlaylist(
        spotify_id="playlist-id",
        name="Small",
        total_tracks=1,
        tracks=(
            SpotifyTrack(
                "Song",
                ("Artist",),
                120,
                "NO1234567890",
                "spotify-track",
            ),
        ),
    )
    source = SourceConfig(
        spotify_playlist_id="playlist-id",
        navidrome_playlist_name="Small Downloader Test",
        download_missing=True,
        download_target="small-test",
        cleanup_downloads=True,
    )
    runtime = RuntimeConfig(
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
        navidrome_url="https://navidrome.example.org",
        navidrome_username="user",
        navidrome_password="password",
        download_root=tmp_path,
        navidrome_scan_timeout_seconds=7,
        dry_run=True,
    )
    target = tmp_path / "small-test"
    target.mkdir()
    stale_path = target / "Stale_-_Song_-_stale-track.mp3"
    stale_path.write_text("stale", encoding="utf-8")
    write_manifest(
        target,
        (
            ManifestEntry(
                "stale-track",
                None,
                "Stale",
                "Song",
                stale_path,
            ),
        ),
    )

    report = _sync_playlist(
        cast(NavidromeClient, navidrome),
        downloader,
        playlist,
        source,
        runtime,
    )

    assert downloader.downloaded == []
    assert navidrome.replaced_song_ids == ()
    assert navidrome.events == ["search:Artist Song"]
    assert stale_path.exists()
    assert [entry.spotify_id for entry in load_manifest(target)] == ["stale-track"]
    assert report.action == "dry-run"
    assert report.navidrome_playlist_id is None
    assert report.matched == 0
    assert report.missing == 1
    assert report.downloaded == 1
    assert report.cleaned_up == 1
    assert report.diagnostics[0].status == "missing"


def test_print_report_includes_unresolved_track_diagnostics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    navidrome = FakeNavidrome()
    downloader = FakeDownloader()
    playlist = SpotifyPlaylist(
        spotify_id="playlist-id",
        name="Small",
        total_tracks=1,
        tracks=(SpotifyTrack("Song", ("Artist",), 120, "NO1234567890", "spotify-track"),),
    )
    source = SourceConfig(
        spotify_playlist_id="playlist-id",
        navidrome_playlist_name="Small Downloader Test",
    )
    runtime = RuntimeConfig(
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
        navidrome_url="https://navidrome.example.org",
        navidrome_username="user",
        navidrome_password="password",
        dry_run=True,
    )
    report = _sync_playlist(
        cast(NavidromeClient, navidrome),
        downloader,
        playlist,
        source,
        runtime,
    )

    _print_report(RunReport(dry_run=True, playlists=(report,)))

    captured = capsys.readouterr()
    assert "spotify-navidrome-sync report" in captured.out
    assert "mode: dry-run" in captured.out
    assert "playlist: Small (playlist-id)" in captured.out
    assert "tracks: fetched=1 reported_total=1 matched=0 missing=1 ambiguous=0" in captured.out
    assert "downloads_planned: 0" in captured.out
    assert (
        "status=missing spotify=Artist - Song spotify_id=spotify-track isrc=NO1234567890"
        in captured.out
    )
