from __future__ import annotations

from pathlib import Path

from spotify_navidrome_sync.navidrome import NavidromeSong

NAVIDROME_RIP_PREFIX = "/music/rip/"


def filter_stale_rip_candidates(
    candidates: tuple[NavidromeSong, ...],
    *,
    download_root: Path,
) -> tuple[NavidromeSong, ...]:
    return tuple(
        candidate
        for candidate in candidates
        if not _is_missing_mounted_rip_file(candidate, download_root=download_root)
    )


def target_dir(download_root: Path, download_target: str) -> Path:
    root = download_root.resolve()
    candidate = (root / download_target).resolve()
    if candidate.parent != root:
        raise ValueError(f"download target escapes download root: {download_target!r}")
    return candidate


def rip_song_path(song: NavidromeSong, *, download_root: Path) -> Path | None:
    raw_path = song.raw.get("path")
    if not isinstance(raw_path, str) or not raw_path.startswith(NAVIDROME_RIP_PREFIX):
        return None
    relative = raw_path.removeprefix(NAVIDROME_RIP_PREFIX)
    if not relative or relative.startswith("/"):
        return None
    root = download_root.resolve()
    mapped = (root / relative).resolve()
    try:
        mapped.relative_to(root)
    except ValueError:
        return None
    return mapped


def _is_missing_mounted_rip_file(song: NavidromeSong, *, download_root: Path) -> bool:
    mapped = rip_song_path(song, download_root=download_root)
    return mapped is not None and not mapped.exists()
