from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("spotify_navidrome_sync")

MANIFEST_NAME = ".spotify-navidrome-sync.json"


class ManifestError(RuntimeError):
    """Raised when app-owned downloaded-file metadata is invalid."""


@dataclass(frozen=True)
class ManifestEntry:
    spotify_id: str
    isrc: str | None
    artist: str
    title: str
    path: Path


def manifest_path(directory: Path) -> Path:
    return directory / MANIFEST_NAME


def load_manifest(directory: Path) -> tuple[ManifestEntry, ...]:
    path = manifest_path(directory)
    if not path.exists():
        return ()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"failed to read manifest {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ManifestError(f"manifest {path} has unsupported format")
    files = raw.get("files")
    if not isinstance(files, list):
        raise ManifestError(f"manifest {path} files must be a list")
    entries: list[ManifestEntry] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        spotify_id = item.get("spotify_id")
        artist = item.get("artist")
        title = item.get("title")
        raw_path = item.get("path")
        if not isinstance(spotify_id, str) or not spotify_id:
            continue
        if not isinstance(artist, str) or not artist:
            continue
        if not isinstance(title, str) or not title:
            continue
        if not isinstance(raw_path, str) or not raw_path:
            continue
        isrc = item.get("isrc")
        entries.append(
            ManifestEntry(
                spotify_id=spotify_id,
                isrc=isrc if isinstance(isrc, str) and isrc else None,
                artist=artist,
                title=title,
                path=Path(raw_path),
            )
        )
    return tuple(entries)


def write_manifest(directory: Path, entries: tuple[ManifestEntry, ...]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "version": 1,
        "files": [
            {
                "spotify_id": entry.spotify_id,
                "isrc": entry.isrc,
                "artist": entry.artist,
                "title": entry.title,
                "path": str(entry.path),
            }
            for entry in sorted(entries, key=lambda entry: entry.spotify_id)
        ],
    }
    manifest_path(directory).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def cleanup_manifest_files(directory: Path, keep_spotify_ids: set[str]) -> int:
    entries = load_manifest(directory)
    remaining: list[ManifestEntry] = []
    deleted = 0

    root = directory.resolve()
    for entry in entries:
        if entry.spotify_id in keep_spotify_ids:
            remaining.append(entry)
            continue

        path = entry.path.resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise ManifestError(f"manifest file path escapes target directory: {entry.path}")

        if path == manifest_path(root):
            raise ManifestError("manifest attempted to delete itself")

        if path.exists():
            path.unlink()
            deleted += 1
            LOGGER.info("deleted app-owned downloaded file %s", path)

    write_manifest(directory, tuple(remaining))
    return deleted


def merge_manifest_entries(
    existing: tuple[ManifestEntry, ...],
    updates: tuple[ManifestEntry, ...],
) -> tuple[ManifestEntry, ...]:
    merged = {entry.spotify_id: entry for entry in existing}
    for entry in updates:
        merged[entry.spotify_id] = entry
    return tuple(merged.values())
