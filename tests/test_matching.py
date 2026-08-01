from __future__ import annotations

from spotify_navidrome_sync.matching import match_track, normalize
from spotify_navidrome_sync.navidrome import NavidromeSong
from spotify_navidrome_sync.spotify import SpotifyTrack


def test_normalize_removes_case_punctuation_and_accents() -> None:
    assert normalize("Beyoncé - Déjà Vu!") == "beyonce deja vu"


def test_match_track_matches_isrc_from_candidate_isrcs() -> None:
    track = SpotifyTrack(
        name="Song",
        artists=("Artist",),
        duration_seconds=120,
        isrc="NO1234567890",
        spotify_id="spotify-track",
    )
    song = NavidromeSong(
        id="navidrome-song",
        title="Different Title",
        artist="Different Artist",
        duration_seconds=999,
        suffix="flac",
        isrcs=("NO1234567890",),
        raw={"path": "Artist/Album/01 - Song.flac"},
    )

    result = match_track(track, (song,))

    assert result.status == "matched"
    assert result.matched_song == song


def test_match_track_prefers_flac_for_equivalent_normalized_matches() -> None:
    track = SpotifyTrack(
        name="Song",
        artists=("Artist",),
        duration_seconds=120,
        isrc=None,
        spotify_id="spotify-track",
    )
    first = NavidromeSong(
        "one",
        "Song",
        "Artist",
        120,
        "mp3",
        (),
        {"path": "Artist/Album/01 - Song.mp3"},
    )
    second = NavidromeSong(
        "two",
        "Song",
        "Artist",
        120,
        "flac",
        (),
        {"path": "Artist/Album/01 - Song.flac"},
    )

    result = match_track(track, (first, second))

    assert result.status == "matched"
    assert result.matched_song == second


def test_match_track_picks_stable_candidate_when_multiple_flacs_match() -> None:
    track = SpotifyTrack(
        name="Song",
        artists=("Artist",),
        duration_seconds=120,
        isrc="NO1234567890",
        spotify_id="spotify-track",
    )
    second_path = NavidromeSong(
        "two",
        "Song",
        "Artist",
        120,
        "flac",
        ("NO1234567890",),
        {"path": "Artist/Z Album/01 - Song.flac"},
    )
    first_path = NavidromeSong(
        "one",
        "Song",
        "Artist",
        120,
        "flac",
        ("NO1234567890",),
        {"path": "Artist/A Album/01 - Song.flac"},
    )

    result = match_track(track, (second_path, first_path))

    assert result.status == "matched"
    assert result.matched_song == first_path


def test_match_track_uses_duration_tolerance() -> None:
    track = SpotifyTrack(
        name="Song",
        artists=("Artist",),
        duration_seconds=120,
        isrc=None,
        spotify_id="spotify-track",
    )
    too_long = NavidromeSong("one", "Song", "Artist", 130, "flac", (), {})

    result = match_track(track, (too_long,))

    assert result.status == "missing"
