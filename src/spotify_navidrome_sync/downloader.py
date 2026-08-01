from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from spotify_navidrome_sync.manifest import ManifestEntry
from spotify_navidrome_sync.spotify import SpotifyTrack

LOGGER = logging.getLogger("spotify_navidrome_sync")

SPOTIFY_TRACK_URL = "https://open.spotify.com/track/{spotify_id}"
OUTPUT_TEMPLATE = "{artist}_-_{title}_-_{track-id}.{output-ext}"


class DownloadError(RuntimeError):
    """Raised when downloading missing tracks fails."""


class SpotdlDownloader:
    def __init__(
        self,
        *,
        binary: str,
        spotify_client_id: str,
        spotify_client_secret: str,
        format_name: str = "mp3",
        chunk_size: int = 25,
    ) -> None:
        self._binary = binary
        self._spotify_client_id = spotify_client_id
        self._spotify_client_secret = spotify_client_secret
        self._format_name = format_name
        self._chunk_size = chunk_size

    def download_missing(
        self,
        tracks: Sequence[SpotifyTrack],
        *,
        target_dir: Path,
    ) -> tuple[ManifestEntry, ...]:
        downloadable = tuple(track for track in tracks if track.spotify_id)
        skipped = len(tracks) - len(downloadable)
        if skipped:
            LOGGER.warning("skipping %d missing track(s) without Spotify track IDs", skipped)
        if not downloadable:
            return ()

        target_dir.mkdir(parents=True, exist_ok=True)
        for chunk in _chunks(downloadable, self._chunk_size):
            command = self.build_command(chunk, target_dir=target_dir)
            LOGGER.info("downloading %d missing track(s) with spotDL", len(chunk))
            result = subprocess.run(
                command,
                check=False,
                cwd=target_dir,
                env={**os.environ, "HOME": os.environ.get("HOME", "/tmp")},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=None,
            )
            if result.returncode != 0:
                raise DownloadError(_failure_message(result.stdout))

        entries: list[ManifestEntry] = []
        for track in downloadable:
            entry = _manifest_entry(track, target_dir=target_dir)
            if entry is None:
                LOGGER.warning(
                    "spotDL completed but no downloaded file was found for %s - %s (%s)",
                    track.primary_artist,
                    track.name,
                    track.spotify_id,
                )
                continue
            entries.append(entry)

        return tuple(entries)

    def build_command(self, tracks: Sequence[SpotifyTrack], *, target_dir: Path) -> list[str]:
        urls = [
            SPOTIFY_TRACK_URL.format(spotify_id=track.spotify_id)
            for track in tracks
            if track.spotify_id
        ]
        if not urls:
            raise DownloadError("cannot build spotDL command without Spotify track IDs")
        return [
            self._binary,
            "--no-cache",
            "--client-id",
            self._spotify_client_id,
            "--client-secret",
            self._spotify_client_secret,
            "--format",
            self._format_name,
            "--output",
            str(target_dir / OUTPUT_TEMPLATE),
            "download",
            *urls,
        ]


def _chunks(tracks: Sequence[SpotifyTrack], size: int) -> tuple[tuple[SpotifyTrack, ...], ...]:
    return tuple(tuple(tracks[index : index + size]) for index in range(0, len(tracks), size))


def _manifest_entry(track: SpotifyTrack, *, target_dir: Path) -> ManifestEntry | None:
    if track.spotify_id is None:
        raise DownloadError("downloaded track did not have a Spotify ID")

    matches = sorted(target_dir.glob(f"*-_{track.spotify_id}.mp3"))
    if not matches:
        matches = sorted(target_dir.glob(f"{track.spotify_id}_-*.mp3"))
    if not matches:
        return None
    if len(matches) > 1:
        raise DownloadError(f"multiple downloaded files found for Spotify track {track.spotify_id}")

    return ManifestEntry(
        spotify_id=track.spotify_id,
        isrc=track.isrc,
        artist=track.primary_artist,
        title=track.name,
        path=matches[0],
    )


def _failure_message(output: str) -> str:
    stripped = output.strip()
    if not stripped:
        return "spotDL download failed without output"
    return f"spotDL download failed: {stripped[-2000:]}"
