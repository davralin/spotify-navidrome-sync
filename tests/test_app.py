from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import cast

from spotify_navidrome_sync.app import _sync_playlist
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

    _sync_playlist(
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
