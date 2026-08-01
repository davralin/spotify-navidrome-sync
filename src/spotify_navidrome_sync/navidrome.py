from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

import httpx


class NavidromeError(RuntimeError):
    """Raised when Navidrome API access fails."""


@dataclass(frozen=True)
class NavidromeSong:
    id: str
    title: str
    artist: str
    duration_seconds: int | None
    suffix: str | None
    isrcs: tuple[str, ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class NavidromePlaylist:
    id: str
    name: str


class NavidromeClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        http: httpx.Client | None = None,
    ) -> None:
        self._base_url = _normalize_rest_url(base_url)
        self._username = username
        self._password = password
        self._http = http or httpx.Client(timeout=30.0)

    def ping(self) -> dict[str, Any]:
        return self._request("ping", [])

    def search_songs(self, query: str, *, count: int = 10) -> tuple[NavidromeSong, ...]:
        payload = self._request(
            "search3",
            [
                ("query", query),
                ("artistCount", "0"),
                ("albumCount", "0"),
                ("songCount", str(count)),
            ],
        )
        result = payload.get("searchResult3")
        if not isinstance(result, dict):
            return ()
        return tuple(_parse_song(song) for song in _list_value(result.get("song")))

    def get_playlists(self) -> tuple[NavidromePlaylist, ...]:
        payload = self._request("getPlaylists", [])
        playlists = payload.get("playlists")
        if not isinstance(playlists, dict):
            return ()
        return tuple(_parse_playlist(item) for item in _list_value(playlists.get("playlist")))

    def replace_playlist(self, name: str, song_ids: tuple[str, ...]) -> str:
        if not song_ids:
            raise NavidromeError(
                f"refusing to create or update playlist {name!r} with zero matched songs"
            )

        matches = [playlist for playlist in self.get_playlists() if playlist.name == name]
        if len(matches) > 1:
            raise NavidromeError(
                f"multiple Navidrome playlists are named {name!r}; refusing to guess"
            )

        params: list[tuple[str, str]] = []
        if matches:
            params.append(("playlistId", matches[0].id))
        else:
            params.append(("name", name))
        params.extend(("songId", song_id) for song_id in song_ids)

        payload = self._request("createPlaylist", params)
        playlist = payload.get("playlist")
        playlist_id = playlist.get("id") if isinstance(playlist, dict) else None
        if isinstance(playlist_id, str):
            return playlist_id
        if matches:
            return matches[0].id
        raise NavidromeError(f"Navidrome did not return a playlist id for {name!r}")

    def _request(self, endpoint: str, params: list[tuple[str, str]]) -> dict[str, Any]:
        body = str(httpx.QueryParams([*self._auth_params(), *params]))
        response = self._http.post(
            f"{self._base_url}/{endpoint}.view",
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise NavidromeError(
                f"Navidrome {endpoint} failed: HTTP {exc.response.status_code}"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise NavidromeError(f"Navidrome {endpoint} response was not JSON") from exc
        if not isinstance(payload, dict):
            raise NavidromeError(f"Navidrome {endpoint} response was not an object")
        inner = payload.get("subsonic-response")
        if not isinstance(inner, dict):
            raise NavidromeError(f"Navidrome {endpoint} response did not contain subsonic-response")
        if inner.get("status") != "ok":
            error = inner.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            raise NavidromeError(f"Navidrome {endpoint} failed: {message or 'unknown error'}")
        return inner

    def _auth_params(self) -> list[tuple[str, str]]:
        salt = secrets.token_hex(8)
        token = hashlib.md5(f"{self._password}{salt}".encode()).hexdigest()
        return [
            ("u", self._username),
            ("t", token),
            ("s", salt),
            ("v", "1.16.1"),
            ("c", "spotify-navidrome-sync"),
            ("f", "json"),
        ]


def _normalize_rest_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith("/rest"):
        return stripped
    return f"{stripped}/rest"


def _parse_song(raw: object) -> NavidromeSong:
    if not isinstance(raw, dict):
        return NavidromeSong("", "", "", None, None, (), {})
    return NavidromeSong(
        id=str(raw.get("id") or ""),
        title=str(raw.get("title") or ""),
        artist=str(raw.get("artist") or ""),
        duration_seconds=raw.get("duration") if isinstance(raw.get("duration"), int) else None,
        suffix=raw.get("suffix") if isinstance(raw.get("suffix"), str) else None,
        isrcs=_parse_isrcs(raw.get("isrc")),
        raw=raw,
    )


def _parse_isrcs(raw: object) -> tuple[str, ...]:
    values = raw if isinstance(raw, list) else [raw]
    isrcs: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        for part in value.replace(";", ",").split(","):
            isrc = part.strip().upper()
            if isrc and isrc not in isrcs:
                isrcs.append(isrc)
    return tuple(isrcs)


def _parse_playlist(raw: object) -> NavidromePlaylist:
    if not isinstance(raw, dict):
        return NavidromePlaylist("", "")
    return NavidromePlaylist(id=str(raw.get("id") or ""), name=str(raw.get("name") or ""))


def _list_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []
