# spotify-navidrome-sync

One-shot container job for syncing configured Spotify playlists into Navidrome playlists.

Spotify is the authoritative source for playlist order and membership. The job reads configured public Spotify playlists, searches the Navidrome library for matching local tracks, and creates or updates Navidrome playlists with the matched tracks in Spotify order.

The initial implementation does not download missing tracks, does not run `spotdl`, does not trigger Navidrome scans, and does not delete media files.

## Configuration

Runtime credentials are environment variables:

```sh
SPOTIFY_CLIENT_ID=your_spotify_app_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_app_client_secret
NAVIDROME_URL=https://navidrome.example.org
NAVIDROME_USERNAME=your_navidrome_username
NAVIDROME_PASSWORD=your_navidrome_password
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
    download_missing: false
```

Unknown config keys are ignored.

Required source fields:

- `spotify_playlist_id`
- `navidrome_playlist_name`

Optional source fields:

- `download_missing`, default `false`; `true` is not implemented yet

See `examples/config.yaml` for a complete multi-playlist example.

## Matching

For each Spotify track, the job searches Navidrome and chooses a local song using conservative matching:

- ISRC match when available
- normalized title and artist fallback
- duration tolerance
- FLAC preference when equivalent local candidates exist

Tracks that cannot be matched safely are skipped and counted as `missing` or `ambiguous` in the final log line for each playlist. Spotify remains authoritative for playlist ordering.

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
  -v "$PWD/examples/config.yaml:/config/config.yaml:ro" \
  spotify-navidrome-sync:local \
  /config/config.yaml
```

For real local runs, keep your own config file outside the repository and mount that file instead of `examples/config.yaml`.

The command creates or replaces matching Navidrome playlists. It does not download missing tracks, run `spotdl`, trigger a Navidrome scan, or delete media.

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

See `adr/0009-sync-configured-spotify-playlists-with-client-credentials.md` for the current sync scope.
