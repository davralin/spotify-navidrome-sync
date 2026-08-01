from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence

from spotify_navidrome_sync.config import ConfigError, load_app_config, load_runtime_config
from spotify_navidrome_sync.matching import match_track, search_query
from spotify_navidrome_sync.navidrome import NavidromeClient, NavidromeError
from spotify_navidrome_sync.spotify import SpotifyClient, SpotifyError, SpotifyPlaylist

LOGGER = logging.getLogger("spotify_navidrome_sync")


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
        navidrome.ping()

        LOGGER.info("loaded %d playlist source(s)", len(app_config.sources))
        for source in app_config.sources:
            playlist = spotify.get_playlist(source.spotify_playlist_id)
            _sync_playlist(navidrome, playlist, source.navidrome_playlist_name)
    except (ConfigError, SpotifyError, NavidromeError) as exc:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        LOGGER.error("%s", exc)
        return 1

    return 0


def _sync_playlist(
    navidrome: NavidromeClient,
    playlist: SpotifyPlaylist,
    navidrome_playlist_name: str,
) -> None:
    LOGGER.info(
        "syncing Spotify playlist %r (%d fetched track(s), %d reported total) "
        "to Navidrome playlist %r",
        playlist.name,
        len(playlist.tracks),
        playlist.total_tracks,
        navidrome_playlist_name,
    )

    song_ids: list[str] = []
    matched = 0
    ambiguous = 0
    missing = 0

    for track in playlist.tracks:
        candidates = navidrome.search_songs(search_query(track))
        result = match_track(track, candidates)
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
            LOGGER.debug("missing in Navidrome: %s - %s", track.primary_artist, track.name)

    playlist_id = navidrome.replace_playlist(navidrome_playlist_name, tuple(song_ids))
    LOGGER.info(
        "updated Navidrome playlist %r (%s): matched=%d ambiguous=%d missing=%d",
        navidrome_playlist_name,
        playlist_id,
        matched,
        ambiguous,
        missing,
    )


def _configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level, logging.INFO)
    logging.basicConfig(level=numeric_level, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


if __name__ == "__main__":
    sys.exit(main())
