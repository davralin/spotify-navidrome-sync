# 0009. Sync Configured Spotify Playlists With Client Credentials

Date: 2026-08-01

## Status

Accepted

## Context

This repository builds a one-shot job that keeps Navidrome playlists aligned with configured Spotify playlists.

The first operational target is a local container run that reads public Spotify playlist metadata, finds matching tracks already present in Navidrome, and creates or updates Navidrome playlists. The job is externally scheduled when deployed, for example as a Kubernetes CronJob.

Spotify Liked Songs, user-library data, private playlists, and collaborative playlists require user OAuth scopes and refresh-token handling. That is a different authorization model from public playlist reads and is not required for the initial playlist sync job.

## Decision

The initial implementation syncs explicitly configured Spotify playlists only.

Spotify is the authoritative source for playlist order and membership. The job creates or updates Navidrome playlists so their entries match the successfully matched Spotify tracks in Spotify order.

Spotify authentication uses the Client Credentials flow with `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` supplied by environment variables.

Navidrome credentials are also supplied by environment variables. Credentials are not read from the config file.

The config file contains playlist mappings and non-secret per-source policy:

```yaml
sources:
  - spotify_playlist_id: "4Llq96RL2xSSl1U8LaFxCm"
    navidrome_playlist_name: "Spotify Sync Test - 90s"
    download_missing: false
```

Unknown config keys are ignored. The only required source fields are `spotify_playlist_id` and `navidrome_playlist_name`.

The first implementation does not download missing tracks, does not invoke `spotdl`, does not trigger Navidrome scans, and does not delete media files. `download_missing: true` is reserved for later work and fails until implemented.

Dry-run behavior is also reserved for later work. If `DRY_RUN=true` is set before it is implemented, the job fails clearly instead of pretending to run safely.

## Consequences

The first job can be tested end-to-end with public Spotify playlists and existing Navidrome credentials without implementing browser-based OAuth.

Liked Songs and user-library support remain out of scope until a later ADR introduces a user OAuth model.

The config file stays non-secret and safe to mount from ConfigMaps or local files.

Initial syncs are intentionally conservative: only matched local Navidrome tracks are added to playlists, ambiguous or missing Spotify tracks are reported and excluded, and no fallback download path is used.
