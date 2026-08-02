from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from spotify_navidrome_sync.navidrome import NavidromeSong
from spotify_navidrome_sync.spotify import SpotifyTrack


@dataclass(frozen=True)
class TrackMatch:
    spotify_track: SpotifyTrack
    matched_song: NavidromeSong | None
    ambiguous_songs: tuple[NavidromeSong, ...] = ()

    @property
    def status(self) -> str:
        if self.matched_song is not None:
            return "matched"
        if self.ambiguous_songs:
            return "ambiguous"
        return "missing"


def match_track(track: SpotifyTrack, candidates: tuple[NavidromeSong, ...]) -> TrackMatch:
    candidates = tuple(candidate for candidate in candidates if candidate.id)

    if track.isrc:
        isrc_matches = tuple(candidate for candidate in candidates if track.isrc in candidate.isrcs)
        selected = _select_preferred(isrc_matches)
        if selected is not None:
            return TrackMatch(spotify_track=track, matched_song=selected)

    normalized_title = normalize(track.name)
    normalized_artists = {normalize(artist) for artist in track.artists}
    strict_matches = tuple(
        candidate
        for candidate in candidates
        if _title_compatible(normalize(candidate.title), normalized_title)
        and _artist_compatible(normalize(candidate.artist), normalized_artists)
        and _duration_close(track.duration_seconds, candidate.duration_seconds)
    )

    selected = _select_preferred(strict_matches)
    if selected is not None:
        return TrackMatch(spotify_track=track, matched_song=selected)

    return TrackMatch(spotify_track=track, matched_song=None)


def search_query(track: SpotifyTrack) -> str:
    if track.primary_artist:
        return f"{track.primary_artist} {track.name}"
    return track.name


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in decomposed if not unicodedata.combining(char))
    lowered = ascii_value.casefold()
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def _title_compatible(candidate_title: str, spotify_title: str) -> bool:
    if candidate_title == spotify_title:
        return True
    return candidate_title.startswith(f"{spotify_title} ") or spotify_title.startswith(
        f"{candidate_title} "
    )


def _artist_compatible(candidate_artist: str, spotify_artists: set[str]) -> bool:
    if candidate_artist in spotify_artists:
        return True
    return any(_contains_phrase(candidate_artist, artist) for artist in spotify_artists)


def _contains_phrase(value: str, phrase: str) -> bool:
    return f" {phrase} " in f" {value} "


def _select_preferred(candidates: tuple[NavidromeSong, ...]) -> NavidromeSong | None:
    if not candidates:
        return None
    return sorted(candidates, key=_preference_key)[0]


def _preference_key(candidate: NavidromeSong) -> tuple[int, str, str]:
    suffix = (candidate.suffix or "").casefold()
    path = str(candidate.raw.get("path") or "")
    return (0 if suffix == "flac" else 1, path.casefold(), candidate.id)


def _duration_close(left: int | None, right: int | None) -> bool:
    if left is None or right is None:
        return True
    return abs(left - right) <= 12
