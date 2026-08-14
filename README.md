# spotify-navidrome-sync

One-shot container job for syncing configured Spotify playlists into Navidrome playlists.

Spotify is the authoritative source for playlist order and membership. The job reads configured public Spotify playlists, searches the Navidrome library for matching local tracks, and creates or updates Navidrome playlists with the matched tracks in Spotify order.

Sources can optionally download missing tracks with `spotdl download`. Downloads are app-planned from Navidrome matching results; the job does not use `spotdl sync`, `.spotdl` state files, or `.m3u8` playlist files as playlist state.

## Configuration

Runtime credentials are environment variables:

```sh
SPOTIFY_CLIENT_ID=your_spotify_app_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_app_client_secret
NAVIDROME_URL=https://navidrome.example.org
NAVIDROME_USERNAME=your_navidrome_username
NAVIDROME_PASSWORD=your_navidrome_password
DOWNLOAD_ROOT=/media
SPOTDL_BIN=spotdl
NAVIDROME_SCAN_TIMEOUT_SECONDS=900
DRY_RUN=false
```

Create Spotify app credentials from the Spotify Developer Dashboard. The current sync mode uses Spotify Client Credentials, so configured playlists must be readable without user OAuth.

Playlist mappings live in a YAML config file. `spotify_playlist_id` accepts a Spotify playlist ID or a playlist URL:

```yaml
sources:
  - spotify_playlist_id: "37i9dQZF1DXcBWIGoYBM5M"
    navidrome_playlist_name: "Spotify Today's Top Hits"
    download_missing: false

  - spotify_playlist_id: "https://open.spotify.com/playlist/37i9dQZF1DX4JAvHpjipBk"
    navidrome_playlist_name: "Spotify New Music Friday"
    download_missing: true
    download_target: "new-music-friday"
    cleanup_downloads: true
```

Unknown config keys are ignored.

Required source fields:

- `spotify_playlist_id`
- `navidrome_playlist_name`

Optional source fields:

- `download_missing`, default `false`; when true, download unmatched Spotify tracks
- `download_target`; required when `download_missing` or `cleanup_downloads` is true, and must be a safe single path segment below `DOWNLOAD_ROOT`
- `cleanup_downloads`, default `false`; when true, delete obsolete app-owned files recorded in the target manifest

See `examples/config.yaml` for a complete multi-playlist example.

## Matching

For each Spotify track, the job searches Navidrome and chooses a local song using conservative matching:

- ISRC match when available
- normalized title and artist fallback
- duration tolerance
- FLAC preference when equivalent local candidates exist

Tracks that cannot be matched safely are skipped and counted as `missing` or `ambiguous` in the final log line for each playlist. Spotify remains authoritative for playlist ordering.

For downloader-enabled sources, the first matching pass determines the missing tracks. The job downloads only those explicit Spotify track URLs, starts a Navidrome scan, waits for completion, re-matches the whole playlist, and then replaces the Navidrome playlist.

Only Navidrome `/music/rip/...` paths are mapped back to the local filesystem under `DOWNLOAD_ROOT`. Other Navidrome library paths such as `/music/artists/...` are trusted as indexed library state and are never mutated by this job.

## Dry Run And Report

Set `DRY_RUN=true` to plan a run without mutating Navidrome or the download directory. Dry runs still fetch Spotify playlists, search Navidrome, load manifests, and build the final plan, but they do not run spotDL, start scans, replace playlists, write manifests, or delete files.

Each run prints a final text report to stdout. Logs are still written through normal logging, while the report is intended for CronJob log collection. The report includes one section per playlist with fetched/reported track counts, matched/missing/ambiguous counts, planned or actual download and cleanup counts, the Navidrome playlist action, and unresolved track diagnostics.

## Downloads And Cleanup

Downloaded files are written below `DOWNLOAD_ROOT/<download_target>/` as MP3 files with the Spotify track ID in the filename:

```text
{artist}_-_{title}_-_{track-id}.{output-ext}
```

Each target directory has an app-owned manifest:

```text
.spotify-navidrome-sync.json
```

Cleanup deletes only files listed in that manifest and only when the resolved path remains inside the configured target directory. Files outside the target directory and files not recorded in the manifest are never deleted automatically.

## Run Locally

Build the image:

```sh
docker build -f Containerfile -t spotify-navidrome-sync:local .
```

Run the sync job:

```sh
docker run --rm \
  -e SPOTIFY_CLIENT_ID \
  -e SPOTIFY_CLIENT_SECRET \
  -e NAVIDROME_URL \
  -e NAVIDROME_USERNAME \
  -e NAVIDROME_PASSWORD \
  -e DOWNLOAD_ROOT=/media \
  -v "$PWD/examples/config.yaml:/config/config.yaml:ro" \
  -v "/tmp/spotify-navidrome-sync-media:/media" \
  spotify-navidrome-sync:local \
  /config/config.yaml
```

For real local runs, keep your own config file outside the repository and mount that file instead of `examples/config.yaml`.

For real local downloader tests, use a scratch directory for `/media` first. A local scratch mount can verify spotDL invocation, file placement, manifest cleanup, and the Navidrome scan API call. It cannot prove that your production Navidrome instance indexes the scratch files unless Navidrome is configured to scan that same path.

## Development

```sh
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest tests -v
```

## Scope

Initial Spotify authentication uses Client Credentials and supports configured public playlists. Spotify Liked Songs and other user-library sources are deferred because they require user OAuth and refresh-token handling.

See `adr/0009-sync-configured-spotify-playlists-with-client-credentials.md` for the initial sync scope and `adr/0010-download-missing-spotify-tracks-as-app-owned-rip-files.md` for downloader and cleanup behavior.
