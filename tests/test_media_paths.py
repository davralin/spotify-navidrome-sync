from __future__ import annotations

from pathlib import Path

from spotify_navidrome_sync.media_paths import (
    filter_stale_rip_candidates,
    rip_song_path,
    target_dir,
)
from spotify_navidrome_sync.navidrome import NavidromeSong


def test_rip_song_path_maps_only_navidrome_rip_paths(tmp_path: Path) -> None:
    song = NavidromeSong(
        "song-id",
        "Song",
        "Artist",
        120,
        "mp3",
        (),
        {"path": "/music/rip/90s/Artist_-_Song.mp3"},
    )
    library_song = NavidromeSong(
        "library-id",
        "Song",
        "Artist",
        120,
        "flac",
        (),
        {"path": "/music/artists/Artist/Album/Song.flac"},
    )

    assert rip_song_path(song, download_root=tmp_path) == tmp_path / "90s/Artist_-_Song.mp3"
    assert rip_song_path(library_song, download_root=tmp_path) is None


def test_filter_stale_rip_candidates_keeps_library_matches_but_drops_missing_rip_files(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "90s/Existing.mp3"
    existing.parent.mkdir()
    existing.write_text("existing", encoding="utf-8")
    existing_rip = NavidromeSong(
        "existing", "Existing", "Artist", 120, "mp3", (), {"path": "/music/rip/90s/Existing.mp3"}
    )
    stale_rip = NavidromeSong(
        "stale", "Stale", "Artist", 120, "mp3", (), {"path": "/music/rip/90s/Stale.mp3"}
    )
    library = NavidromeSong(
        "library",
        "Library",
        "Artist",
        120,
        "flac",
        (),
        {"path": "/music/artists/Artist/Album/Library.flac"},
    )

    filtered = filter_stale_rip_candidates(
        (existing_rip, stale_rip, library),
        download_root=tmp_path,
    )

    assert filtered == (existing_rip, library)


def test_target_dir_rejects_escaping_targets(tmp_path: Path) -> None:
    try:
        target_dir(tmp_path, "../escape")
    except ValueError as exc:
        assert "escapes" in str(exc)
    else:
        raise AssertionError("target_dir accepted an escaping target")
