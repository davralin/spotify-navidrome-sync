# 0010. Download Missing Spotify Tracks as App-Owned Rip Files

Date: 2026-08-01

## Status

Accepted

## Context

ADR 0009 introduced Spotify-to-Navidrome playlist sync and reserved `download_missing: true` for later work.

The next iteration must download tracks that are missing from Navidrome, but local downloaded folders are not the authoritative playlist state. For example, the `90s` playlist should reuse existing FLACs from the wider Navidrome library and download only tracks that cannot be matched. In contrast, `BestClassicalMusic` may be fully downloaded when no matching local files exist.

`spotdl sync` is not suitable for this model because it treats a local sync file and download folder as the state for the full Spotify playlist. That would cause unnecessary downloads when matching tracks already exist elsewhere in Navidrome.

The deployed Kubernetes mount intentionally exposes only the rip subtree to the sync job:

```text
PVC subPath: audio/rip
Container:   /media
Navidrome:   /music/rip
```

The job must not be able to mutate `/media/artists`, `/media/singles`, or other library folders.

Navidrome playlist auto-import from `.m3u8` files will be disabled so the sync job is the sole owner of these Spotify-derived playlists.

## Decision

Implement `download_missing: true` as an app-planned download step.

The job will:

1. Fetch the configured Spotify playlist.
2. Match every Spotify track against Navidrome.
3. Prefer existing Navidrome/library matches, including FLACs outside `/music/rip`.
4. Treat only unmatched tracks as download candidates.
5. Download candidates using explicit `spotdl download <track-url>` calls.
6. Write downloads under `/media/<download_target>/` as MP3 files.
7. Trigger a Navidrome scan.
8. Re-match the full Spotify playlist after the scan.
9. Replace the Navidrome playlist through the Subsonic API.
10. Optionally clean up app-owned downloaded files.

The job will not use `spotdl sync`.

The job will not generate `.m3u8` playlist files.

The job will not use `.spotdl` state files as playlist state.

Navidrome `ND_AUTOIMPORTPLAYLISTS` will be set to `false` in the deployment.

## App-Owned Files

Downloaded files are app-owned only when they are under:

```text
/media/<download_target>/
```

and are recorded in the app manifest:

```text
/media/<download_target>/.spotify-navidrome-sync.json
```

Cleanup may delete only files recorded in that manifest and only when the resolved path remains inside `/media/<download_target>/`.

The job must never delete files outside the configured target directory.

The job must never delete files from Navidrome library paths such as:

```text
/music/artists
/music/singles
/music/soundtracks
```

Those paths are not mounted into the sync container and are treated as read-only Navidrome library state.

## Path Mapping

Only rip paths are filesystem-checkable by the sync job.

```text
Navidrome path: /music/rip/<target>/<file>
Sync path:      /media/<target>/<file>
```

For `/music/rip/...` matches, the job may verify that the mapped file exists.

For non-rip paths such as `/music/artists/...`, the job trusts Navidrome's index and may use the track as a playlist candidate, but must not attempt filesystem mutation.

## Config

Per-source config gains:

```yaml
sources:
  - spotify_playlist_id: "4Llq96RL2xSSl1U8LaFxCm"
    navidrome_playlist_name: "90s"
    download_missing: true
    download_target: "90s"
    cleanup_downloads: true
```

`download_target` is relative to `/media`.

`download_target` must be a safe single path segment. Empty values, absolute paths, `..`, and path separators are rejected.

`cleanup_downloads` is explicit because it enables deletion.

Downloaded filenames include the Spotify track ID:

```text
{artist}_-_{title}_-_{track-id}.{output-ext}
```

## Consequences

The `90s` playlist can combine existing FLACs from the Navidrome library with newly downloaded rip files.

`BestClassicalMusic` can be downloaded fully when no library matches exist.

The sync job owns playlist contents through the Subsonic API, avoiding conflicts with Navidrome `.m3u8` auto-import behavior.

Cleanup retains the useful operational behavior of `spotdl sync` without allowing spotDL to decide playlist state or delete unrelated files.

The narrowed Kubernetes mount limits the blast radius of downloader bugs to the rip subtree exposed at `/media`.

Downloaded-file cleanup depends on the app manifest. Files not recorded in the manifest are not deleted automatically.
