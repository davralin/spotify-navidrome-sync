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
from spotify_navidrome_sync.matching import (
    CandidateRejection,
    TrackMatch,
    explain_rejections,
    match_track,
    search_query,
)
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
    diagnostics: tuple[TrackDiagnostic, ...]
    song_ids: tuple[str, ...]
    missing_tracks: tuple[SpotifyTrack, ...]
    matched: int
    ambiguous: int
    missing: int


@dataclass(frozen=True)
class TrackDiagnostic:
    status: str
    title: str
    artists: tuple[str, ...]
    spotify_id: str | None
    isrc: str | None
    navidrome_id: str | None = None
    navidrome_title: str | None = None
    navidrome_artist: str | None = None
    candidates_found: int = 0
    stale_candidates_filtered: int = 0
    rejection_reasons: tuple[str, ...] = ()
    rejected_candidates: tuple[CandidateRejection, ...] = ()


@dataclass(frozen=True)
class PlaylistReport:
    spotify_playlist_id: str
    spotify_playlist_name: str
    spotify_tracks_total: int
    spotify_tracks_fetched: int
    navidrome_playlist_name: str
    matched: int
    ambiguous: int
    missing: int
    downloaded: int
    cleaned_up: int
    dry_run: bool
    action: str
    navidrome_playlist_id: str | None
    diagnostics: tuple[TrackDiagnostic, ...]


@dataclass(frozen=True)
class RunReport:
    dry_run: bool
    playlists: tuple[PlaylistReport, ...]


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
        playlist_reports: list[PlaylistReport] = []
        for source in app_config.sources:
            playlist = spotify.get_playlist(source.spotify_playlist_id)
            playlist_reports.append(
                _sync_playlist(navidrome, downloader, playlist, source, runtime_config)
            )
        _print_report(RunReport(dry_run=runtime_config.dry_run, playlists=tuple(playlist_reports)))
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
) -> PlaylistReport:
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

    downloaded = 0
    cleaned_up = 0
    playlist_id: str | None = None
    action = "dry-run" if runtime.dry_run else "updated"

    if runtime.dry_run:
        if source.download_missing:
            downloaded = len(plan.missing_tracks)
        if source.cleanup_downloads:
            cleaned_up = _count_cleanup_candidates(manifest_entries, playlist)
        if source.download_missing and plan.missing_tracks:
            LOGGER.info(
                "dry run: would download %d missing track(s) for %r",
                len(plan.missing_tracks),
                source.navidrome_playlist_name,
            )
        LOGGER.info(
            "dry run: would replace Navidrome playlist %r with %d matched song(s)",
            source.navidrome_playlist_name,
            len(plan.song_ids),
        )
        if source.cleanup_downloads:
            LOGGER.info(
                "dry run: would clean up %d app-owned file(s) for %r",
                cleaned_up,
                source.navidrome_playlist_name,
            )
        return _playlist_report(
            playlist,
            source,
            plan,
            downloaded=downloaded,
            cleaned_up=cleaned_up,
            dry_run=runtime.dry_run,
            action=action,
            navidrome_playlist_id=playlist_id,
        )

    if source.download_missing and directory is not None and plan.missing_tracks:
        downloaded_entries = downloader.download_missing(plan.missing_tracks, target_dir=directory)
        downloaded = len(downloaded_entries)
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
        cleaned_up = cleanup_manifest_files(
            directory,
            {track.spotify_id for track in playlist.tracks if track.spotify_id is not None},
        )
        if cleaned_up:
            _scan(navidrome, runtime=runtime, reason="after cleaning up downloaded tracks")

    return _playlist_report(
        playlist,
        source,
        plan,
        downloaded=downloaded,
        cleaned_up=cleaned_up,
        dry_run=runtime.dry_run,
        action=action,
        navidrome_playlist_id=playlist_id,
    )


def _plan_playlist(
    navidrome: NavidromeClient,
    playlist: SpotifyPlaylist,
    *,
    runtime: RuntimeConfig,
    manifest_entries: tuple[ManifestEntry, ...] = (),
) -> PlaylistPlan:
    song_ids: list[str] = []
    matches: list[TrackMatch] = []
    diagnostics: list[TrackDiagnostic] = []
    missing_tracks: list[SpotifyTrack] = []
    matched = 0
    ambiguous = 0
    missing = 0

    manifest_by_spotify_id = {
        entry.spotify_id: entry for entry in manifest_entries if entry.spotify_id
    }

    for track in playlist.tracks:
        raw_candidates = navidrome.search_songs(search_query(track))
        candidates = filter_stale_rip_candidates(
            raw_candidates, download_root=runtime.download_root
        )
        stale_candidates_filtered = len(raw_candidates) - len(candidates)
        result = _match_manifest_entry(
            track,
            manifest_by_spotify_id.get(track.spotify_id or ""),
            candidates,
            runtime=runtime,
        ) or match_track(track, candidates)
        matches.append(result)
        diagnostics.append(
            _track_diagnostic(
                result,
                candidates_found=len(raw_candidates),
                stale_candidates_filtered=stale_candidates_filtered,
                rejected_candidates=explain_rejections(track, candidates)
                if result.matched_song is None
                else (),
            )
        )
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
        diagnostics=tuple(diagnostics),
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


def _playlist_report(
    playlist: SpotifyPlaylist,
    source: SourceConfig,
    plan: PlaylistPlan,
    *,
    downloaded: int,
    cleaned_up: int,
    dry_run: bool,
    action: str,
    navidrome_playlist_id: str | None,
) -> PlaylistReport:
    return PlaylistReport(
        spotify_playlist_id=playlist.spotify_id,
        spotify_playlist_name=playlist.name,
        spotify_tracks_total=playlist.total_tracks,
        spotify_tracks_fetched=len(playlist.tracks),
        navidrome_playlist_name=source.navidrome_playlist_name,
        matched=plan.matched,
        ambiguous=plan.ambiguous,
        missing=plan.missing,
        downloaded=downloaded,
        cleaned_up=cleaned_up,
        dry_run=dry_run,
        action=action,
        navidrome_playlist_id=navidrome_playlist_id,
        diagnostics=plan.diagnostics,
    )


def _track_diagnostic(
    match: TrackMatch,
    *,
    candidates_found: int,
    stale_candidates_filtered: int,
    rejected_candidates: tuple[CandidateRejection, ...],
) -> TrackDiagnostic:
    song = match.matched_song
    rejection_reasons = tuple(
        dict.fromkeys(reason for candidate in rejected_candidates for reason in candidate.reasons)
    )
    return TrackDiagnostic(
        status=match.status,
        title=match.spotify_track.name,
        artists=match.spotify_track.artists,
        spotify_id=match.spotify_track.spotify_id,
        isrc=match.spotify_track.isrc,
        navidrome_id=song.id if song is not None else None,
        navidrome_title=song.title if song is not None else None,
        navidrome_artist=song.artist if song is not None else None,
        candidates_found=candidates_found,
        stale_candidates_filtered=stale_candidates_filtered,
        rejection_reasons=rejection_reasons,
        rejected_candidates=rejected_candidates,
    )


def _count_cleanup_candidates(
    manifest_entries: tuple[ManifestEntry, ...],
    playlist: SpotifyPlaylist,
) -> int:
    keep_spotify_ids = {
        track.spotify_id for track in playlist.tracks if track.spotify_id is not None
    }
    return sum(1 for entry in manifest_entries if entry.spotify_id not in keep_spotify_ids)


def _print_report(report: RunReport) -> None:
    print("spotify-navidrome-sync report")
    print(f"mode: {'dry-run' if report.dry_run else 'sync'}")
    print(f"playlists: {len(report.playlists)}")
    for playlist in report.playlists:
        print("")
        print(f"playlist: {playlist.spotify_playlist_name} ({playlist.spotify_playlist_id})")
        print(f"target: {playlist.navidrome_playlist_name}")
        print(f"action: {playlist.action}")
        if playlist.navidrome_playlist_id is not None:
            print(f"navidrome_playlist_id: {playlist.navidrome_playlist_id}")
        print(
            "tracks: "
            f"fetched={playlist.spotify_tracks_fetched} "
            f"reported_total={playlist.spotify_tracks_total} "
            f"matched={playlist.matched} "
            f"missing={playlist.missing} "
            f"ambiguous={playlist.ambiguous}"
        )
        download_label = "downloads_planned" if playlist.dry_run else "downloaded"
        cleanup_label = "cleanup_planned" if playlist.dry_run else "cleaned_up"
        print(f"{download_label}: {playlist.downloaded}")
        print(f"{cleanup_label}: {playlist.cleaned_up}")
        _print_track_diagnostics(playlist)


def _print_track_diagnostics(report: PlaylistReport) -> None:
    unresolved = tuple(
        diagnostic for diagnostic in report.diagnostics if diagnostic.status != "matched"
    )
    if not unresolved:
        print("unresolved_tracks: none")
        return

    print("unresolved_tracks:")
    for diagnostic in unresolved:
        print(
            "  - "
            f"status={diagnostic.status} "
            f"spotify={_spotify_track_label(diagnostic)} "
            f"spotify_id={diagnostic.spotify_id or '-'} "
            f"isrc={diagnostic.isrc or '-'} "
            f"candidates={diagnostic.candidates_found} "
            f"stale_filtered={diagnostic.stale_candidates_filtered} "
            f"reasons={_rejection_reasons_label(diagnostic)}"
        )
        for candidate in diagnostic.rejected_candidates:
            print(f"    rejected: {_candidate_rejection_label(candidate)}")


def _spotify_track_label(diagnostic: TrackDiagnostic) -> str:
    artist = ", ".join(diagnostic.artists) if diagnostic.artists else "Unknown Artist"
    return f"{artist} - {diagnostic.title}"


def _rejection_reasons_label(diagnostic: TrackDiagnostic) -> str:
    if diagnostic.candidates_found == 0:
        return "no_candidates"
    if not diagnostic.rejection_reasons:
        return "none"
    return ",".join(diagnostic.rejection_reasons)


def _candidate_rejection_label(candidate: CandidateRejection) -> str:
    path = candidate.path or "-"
    duration = str(candidate.duration_seconds) if candidate.duration_seconds is not None else "-"
    suffix = candidate.suffix or "-"
    return (
        f"navidrome_id={candidate.navidrome_id or '-'} "
        f"artist={candidate.artist or '-'} "
        f"title={candidate.title or '-'} "
        f"duration={duration} "
        f"suffix={suffix} "
        f"reasons={','.join(candidate.reasons)} "
        f"path={path}"
    )


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
