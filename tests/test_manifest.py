from __future__ import annotations

import json
from pathlib import Path

import pytest

from spotify_navidrome_sync.manifest import (
    ManifestEntry,
    ManifestError,
    cleanup_manifest_files,
    load_manifest,
    write_manifest,
)


def test_manifest_cleanup_deletes_only_unkept_manifest_owned_files(tmp_path: Path) -> None:
    target = tmp_path / "90s"
    target.mkdir()
    keep_file = target / "Artist_-_Keep_-_keep-id.mp3"
    delete_file = target / "Artist_-_Delete_-_delete-id.mp3"
    unmanaged_file = target / "manual.mp3"
    keep_file.write_text("keep", encoding="utf-8")
    delete_file.write_text("delete", encoding="utf-8")
    unmanaged_file.write_text("manual", encoding="utf-8")
    write_manifest(
        target,
        (
            ManifestEntry("keep-id", None, "Artist", "Keep", keep_file),
            ManifestEntry("delete-id", None, "Artist", "Delete", delete_file),
        ),
    )

    deleted = cleanup_manifest_files(target, {"keep-id"})

    assert deleted == 1
    assert keep_file.exists()
    assert not delete_file.exists()
    assert unmanaged_file.exists()
    assert [entry.spotify_id for entry in load_manifest(target)] == ["keep-id"]


def test_manifest_cleanup_rejects_paths_outside_target(tmp_path: Path) -> None:
    target = tmp_path / "90s"
    target.mkdir()
    outside = tmp_path / "outside.mp3"
    outside.write_text("outside", encoding="utf-8")
    (target / ".spotify-navidrome-sync.json").write_text(
        json.dumps(
            {
                "version": 1,
                "files": [
                    {
                        "spotify_id": "outside-id",
                        "isrc": None,
                        "artist": "Artist",
                        "title": "Outside",
                        "path": str(outside),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="escapes target directory"):
        cleanup_manifest_files(target, set())

    assert outside.exists()
