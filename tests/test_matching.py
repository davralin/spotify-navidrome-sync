from __future__ import annotations

from spotify_navidrome_sync.matching import explain_rejections, match_track, normalize
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
    too_long = NavidromeSong("one", "Song", "Artist", 133, "flac", (), {})

    result = match_track(track, (too_long,))

    assert result.status == "missing"


def test_match_track_accepts_combined_artist_tag() -> None:
    track = SpotifyTrack(
        name="Crazy",
        artists=("DJ Goja", "Nito-Onna"),
        duration_seconds=120,
        isrc=None,
        spotify_id="spotify-track",
    )
    song = NavidromeSong("one", "Crazy", "DJ Goja/Nito-Onna", 121, "mp3", (), {})

    result = match_track(track, (song,))

    assert result.status == "matched"
    assert result.matched_song == song


def test_match_track_accepts_small_duration_difference_for_strong_metadata_match() -> None:
    track = SpotifyTrack(
        name="I Will Wait",
        artists=("Mumford & Sons",),
        duration_seconds=276,
        isrc=None,
        spotify_id="spotify-track",
    )
    song = NavidromeSong("one", "I Will Wait", "Mumford & Sons", 287, "mp3", (), {})

    result = match_track(track, (song,))

    assert result.status == "matched"
    assert result.matched_song == song


def test_match_track_accepts_safe_title_suffix_for_strong_artist_duration_match() -> None:
    track = SpotifyTrack(
        name="Unnskyld Agnetha",
        artists=("Anders Mordal",),
        duration_seconds=120,
        isrc=None,
        spotify_id="spotify-track",
    )
    song = NavidromeSong(
        "one",
        "Unnskyld Agnetha - fra Jul i svingen",
        "Anders Mordal",
        120,
        "mp3",
        (),
        {},
    )

    result = match_track(track, (song,))

    assert result.status == "matched"
    assert result.matched_song == song


def test_explain_rejections_reports_candidate_reasons() -> None:
    track = SpotifyTrack(
        name="Song",
        artists=("Artist",),
        duration_seconds=120,
        isrc="NO1234567890",
        spotify_id="spotify-track",
    )
    song = NavidromeSong(
        "one",
        "Other Song",
        "Different Performer",
        160,
        "mp3",
        ("DIFFERENT",),
        {"path": "Artist/Album/01 - Other Song.mp3"},
    )

    rejections = explain_rejections(track, (song,))

    assert len(rejections) == 1
    assert rejections[0].navidrome_id == "one"
    assert rejections[0].reasons == (
        "isrc_mismatch",
        "title_mismatch",
        "artist_mismatch",
        "duration_mismatch",
    )
    assert rejections[0].path == "Artist/Album/01 - Other Song.mp3"
