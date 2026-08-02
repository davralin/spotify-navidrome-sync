from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from spotify_navidrome_sync.config import (
    ConfigError,
    RuntimeConfig,
    SourceConfig,
    load_app_config,
    load_runtime_config,
)
from spotify_navidrome_sync.downloader import DownloadError, SpotdlDownloader
from spotify_navidrome_sync.manifest import (
    ManifestEntry,
    ManifestError,
    cleanup_manifest_files,
    load_manifest,
    merge_manifest_entries,
    write_manifest,
)
from spotify_navidrome_sync.matching import TrackMatch, match_track, search_query
from spotify_navidrome_sync.media_paths import (
    filter_stale_rip_candidates,
    rip_song_path,
    target_dir,
)
from spotify_navidrome_sync.navidrome import NavidromeClient, NavidromeError, NavidromeSong
from spotify_navidrome_sync.spotify import (
    SpotifyClient,
    SpotifyError,
    SpotifyPlaylist,
    SpotifyTrack,
)

LOGGER = logging.getLogger("spotify_navidrome_sync")


@dataclass(frozen=True)
class PlaylistPlan:
    matches: tuple[TrackMatch, ...]
    song_ids: tuple[str, ...]
    missing_tracks: tuple[SpotifyTrack, ...]
    matched: int
    ambiguous: int
    missing: int


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Spotify playlists into Navidrome playlists")
    parser.add_argument("config", help="path to config.yaml")
    args = parser.parse_args(argv)

    try:
        app_config = load_app_config(args.config)
        runtime_config = load_runtime_config(os.environ)
        _configure_logging(runtime_config.log_level)

        spotify = SpotifyClient(
            runtime_config.spotify_client_id,
            runtime_config.spotify_client_secret,
        )
        navidrome = NavidromeClient(
            runtime_config.navidrome_url,
            runtime_config.navidrome_username,
            runtime_config.navidrome_password,
        )
        downloader = SpotdlDownloader(
            binary=runtime_config.spotdl_bin,
            spotify_client_id=runtime_config.spotify_client_id,
            spotify_client_secret=runtime_config.spotify_client_secret,
        )
        navidrome.ping()

        LOGGER.info("loaded %d playlist source(s)", len(app_config.sources))
        for source in app_config.sources:
            playlist = spotify.get_playlist(source.spotify_playlist_id)
            _sync_playlist(navidrome, downloader, playlist, source, runtime_config)
    except (
        ConfigError,
        SpotifyError,
        NavidromeError,
        DownloadError,
        ManifestError,
        ValueError,
    ) as exc:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        LOGGER.error("%s", exc)
        return 1

    return 0


def _sync_playlist(
    navidrome: NavidromeClient,
    downloader: SpotdlDownloader,
    playlist: SpotifyPlaylist,
    source: SourceConfig,
    runtime: RuntimeConfig,
) -> None:
    LOGGER.info(
        "syncing Spotify playlist %r (%d fetched track(s), %d reported total) "
        "to Navidrome playlist %r",
        playlist.name,
        len(playlist.tracks),
        playlist.total_tracks,
        source.navidrome_playlist_name,
    )

    directory = None
    manifest_entries: tuple[ManifestEntry, ...] = ()
    if source.download_target is not None:
        directory = target_dir(runtime.download_root, source.download_target)
        manifest_entries = load_manifest(directory)

    plan = _plan_playlist(
        navidrome,
        playlist,
        runtime=runtime,
        manifest_entries=manifest_entries,
    )

    if source.download_missing and directory is not None and plan.missing_tracks:
        downloaded_entries = downloader.download_missing(plan.missing_tracks, target_dir=directory)
        if downloaded_entries:
            manifest_entries = merge_manifest_entries(manifest_entries, downloaded_entries)
            write_manifest(directory, manifest_entries)
            _scan(navidrome, runtime=runtime, reason="after downloading missing tracks")
            plan = _plan_playlist(
                navidrome,
                playlist,
                runtime=runtime,
                manifest_entries=manifest_entries,
            )
        else:
            LOGGER.warning("spotDL did not create any files for missing tracks")
    elif source.download_missing:
        LOGGER.info("no missing tracks require download for %r", source.navidrome_playlist_name)

    playlist_id = navidrome.replace_playlist(source.navidrome_playlist_name, plan.song_ids)
    LOGGER.info(
        "updated Navidrome playlist %r (%s): matched=%d ambiguous=%d missing=%d",
        source.navidrome_playlist_name,
        playlist_id,
        plan.matched,
        plan.ambiguous,
        plan.missing,
    )

    if source.cleanup_downloads and directory is not None and source.download_target is not None:
        deleted = cleanup_manifest_files(
            directory,
            {track.spotify_id for track in playlist.tracks if track.spotify_id is not None},
        )
        if deleted:
            _scan(navidrome, runtime=runtime, reason="after cleaning up downloaded tracks")


def _plan_playlist(
    navidrome: NavidromeClient,
    playlist: SpotifyPlaylist,
    *,
    runtime: RuntimeConfig,
    manifest_entries: tuple[ManifestEntry, ...] = (),
) -> PlaylistPlan:
    song_ids: list[str] = []
    matches: list[TrackMatch] = []
    missing_tracks: list[SpotifyTrack] = []
    matched = 0
    ambiguous = 0
    missing = 0

    manifest_by_spotify_id = {
        entry.spotify_id: entry for entry in manifest_entries if entry.spotify_id
    }

    for track in playlist.tracks:
        candidates = filter_stale_rip_candidates(
            navidrome.search_songs(search_query(track)),
            download_root=runtime.download_root,
        )
        result = _match_manifest_entry(
            track,
            manifest_by_spotify_id.get(track.spotify_id or ""),
            candidates,
            runtime=runtime,
        ) or match_track(track, candidates)
        matches.append(result)
        if result.matched_song is not None:
            matched += 1
            song_ids.append(result.matched_song.id)
            continue
        if result.ambiguous_songs:
            ambiguous += 1
            LOGGER.debug(
                "ambiguous match: %s - %s (%d candidates)",
                track.primary_artist,
                track.name,
                len(result.ambiguous_songs),
            )
        else:
            missing += 1
            missing_tracks.append(track)
            LOGGER.debug("missing in Navidrome: %s - %s", track.primary_artist, track.name)

    return PlaylistPlan(
        matches=tuple(matches),
        song_ids=tuple(song_ids),
        missing_tracks=tuple(missing_tracks),
        matched=matched,
        ambiguous=ambiguous,
        missing=missing,
    )


def _match_manifest_entry(
    track: SpotifyTrack,
    entry: ManifestEntry | None,
    candidates: tuple[NavidromeSong, ...],
    *,
    runtime: RuntimeConfig,
) -> TrackMatch | None:
    if entry is None:
        return None

    expected_path = entry.path.resolve()
    for candidate in candidates:
        if _candidate_path_matches_manifest(candidate, expected_path, runtime=runtime):
            return TrackMatch(spotify_track=track, matched_song=candidate)

    return None


def _candidate_path_matches_manifest(
    candidate: NavidromeSong,
    expected_path: Path,
    *,
    runtime: RuntimeConfig,
) -> bool:
    mapped_path = rip_song_path(candidate, download_root=runtime.download_root)
    if mapped_path is not None and mapped_path.resolve() == expected_path:
        return True

    raw_path = candidate.raw.get("path")
    if not isinstance(raw_path, str):
        return False
    try:
        relative_expected = expected_path.relative_to(runtime.download_root.resolve())
    except ValueError:
        return False
    return raw_path == str(relative_expected)


def _scan(navidrome: NavidromeClient, *, runtime: RuntimeConfig, reason: str) -> None:
    LOGGER.info("starting Navidrome scan %s", reason)
    navidrome.start_scan()
    navidrome.wait_for_scan_completion(timeout_seconds=runtime.navidrome_scan_timeout_seconds)
    LOGGER.info("Navidrome scan completed %s", reason)


def _configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level, logging.INFO)
    logging.basicConfig(level=numeric_level, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


if __name__ == "__main__":
    sys.exit(main())
