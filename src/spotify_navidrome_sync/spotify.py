from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


class SpotifyError(RuntimeError):
    """Raised when Spotify API access fails."""


@dataclass(frozen=True)
class SpotifyTrack:
    name: str
    artists: tuple[str, ...]
    duration_seconds: int | None
    isrc: str | None
    spotify_id: str | None

    @property
    def primary_artist(self) -> str:
        return self.artists[0] if self.artists else ""


@dataclass(frozen=True)
class SpotifyPlaylist:
    spotify_id: str
    name: str
    total_tracks: int
    tracks: tuple[SpotifyTrack, ...]


class SpotifyClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        http: httpx.Client | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http or httpx.Client(timeout=30.0)
        self._access_token: str | None = None

    def get_playlist(self, playlist_ref: str) -> SpotifyPlaylist:
        playlist_id = extract_playlist_id(playlist_ref)
        token = self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        response = self._http.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}",
            headers=headers,
            params={"fields": "id,name,tracks(total)"},
        )
        payload = _json_response(response, "fetch Spotify playlist")
        tracks_payload = payload.get("tracks")
        if not isinstance(tracks_payload, dict):
            raise SpotifyError("Spotify playlist response did not contain tracks")

        items: list[object] = []
        next_url: object = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        track_fields = "next,items(track(id,name,duration_ms,is_local,external_ids,artists(name)))"
        page_params: dict[str, str] | None = {
            "limit": "100",
            "fields": track_fields,
            "additional_types": "track",
        }
        while isinstance(next_url, str) and next_url:
            page_response = self._http.get(
                next_url,
                headers=headers,
                params=page_params,
            )
            page = _json_response(page_response, "fetch Spotify playlist page")
            items.extend(_list_value(page.get("items")))
            next_url = page.get("next")
            page_params = None

        return SpotifyPlaylist(
            spotify_id=str(payload.get("id") or playlist_id),
            name=str(payload.get("name") or playlist_id),
            total_tracks=_int_value(tracks_payload.get("total")),
            tracks=tuple(_parse_tracks(items)),
        )

    def _get_access_token(self) -> str:
        if self._access_token is not None:
            return self._access_token

        response = self._http.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
        )
        payload = _json_response(response, "request Spotify access token")
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise SpotifyError("Spotify token response did not contain an access token")
        self._access_token = token
        return token


def extract_playlist_id(playlist_ref: str) -> str:
    value = playlist_ref.strip()
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "playlist":
            return parts[1]
        raise SpotifyError(f"unsupported Spotify playlist URL: {playlist_ref}")
    return value


def _parse_tracks(items: list[object]) -> list[SpotifyTrack]:
    tracks: list[SpotifyTrack] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        track = item.get("track")
        if not isinstance(track, dict) or track.get("is_local") is True:
            continue
        name = track.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        artists_raw = _list_value(track.get("artists"))
        artists = tuple(
            artist["name"].strip()
            for artist in artists_raw
            if isinstance(artist, dict)
            and isinstance(artist.get("name"), str)
            and artist["name"].strip()
        )
        external_ids = track.get("external_ids")
        isrc = external_ids.get("isrc") if isinstance(external_ids, dict) else None
        duration_ms = track.get("duration_ms")
        duration_seconds = round(duration_ms / 1000) if isinstance(duration_ms, int) else None
        spotify_id = track.get("id")
        tracks.append(
            SpotifyTrack(
                name=name.strip(),
                artists=artists,
                duration_seconds=duration_seconds,
                isrc=isrc.strip().upper() if isinstance(isrc, str) and isrc.strip() else None,
                spotify_id=spotify_id if isinstance(spotify_id, str) and spotify_id else None,
            )
        )
    return tracks


def _json_response(response: httpx.Response, action: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SpotifyError(f"failed to {action}: HTTP {exc.response.status_code}") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise SpotifyError(f"failed to {action}: response was not JSON") from exc
    if not isinstance(payload, dict):
        raise SpotifyError(f"failed to {action}: response was not an object")
    return payload


def _list_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _int_value(value: object) -> int:
    return value if isinstance(value, int) else 0
