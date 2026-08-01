from __future__ import annotations

import httpx

from spotify_navidrome_sync.spotify import SpotifyClient, extract_playlist_id


def test_extract_playlist_id_accepts_plain_id() -> None:
    assert extract_playlist_id("4Llq96RL2xSSl1U8LaFxCm") == "4Llq96RL2xSSl1U8LaFxCm"


def test_extract_playlist_id_accepts_spotify_url() -> None:
    assert (
        extract_playlist_id("https://open.spotify.com/playlist/4Llq96RL2xSSl1U8LaFxCm?si=abc")
        == "4Llq96RL2xSSl1U8LaFxCm"
    )


def test_get_playlist_fetches_all_track_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "token"})
        if request.url.path == "/v1/playlists/playlist-id":
            return httpx.Response(
                200,
                json={"id": "playlist-id", "name": "Playlist", "tracks": {"total": 2}},
            )
        if request.url.params.get("offset") == "100":
            return httpx.Response(
                200,
                json={"next": None, "items": [_track_item("second")]},
            )
        return httpx.Response(
            200,
            json={
                "next": "https://api.spotify.com/v1/playlists/playlist-id/tracks?offset=100",
                "items": [_track_item("first")],
            },
        )

    playlist = SpotifyClient(
        "client-id",
        "client-secret",
        httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.spotify.com"),
    ).get_playlist("playlist-id")

    assert [track.name for track in playlist.tracks] == ["first", "second"]


def test_get_playlist_refreshes_expired_token_on_unauthorized() -> None:
    tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            token = f"token-{len(tokens) + 1}"
            tokens.append(token)
            return httpx.Response(200, json={"access_token": token, "expires_in": 3600})
        if request.url.path == "/v1/playlists/playlist-id":
            if request.headers.get("Authorization") == "Bearer token-1":
                return httpx.Response(401, json={"error": {"message": "expired"}})
            return httpx.Response(
                200,
                json={"id": "playlist-id", "name": "Playlist", "tracks": {"total": 1}},
            )
        return httpx.Response(200, json={"next": None, "items": [_track_item("first")]})

    playlist = SpotifyClient(
        "client-id",
        "client-secret",
        httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.spotify.com"),
    ).get_playlist("playlist-id")

    assert tokens == ["token-1", "token-2"]
    assert [track.name for track in playlist.tracks] == ["first"]


def _track_item(name: str) -> dict[str, object]:
    return {
        "track": {
            "id": name,
            "name": name,
            "duration_ms": 120000,
            "external_ids": {},
            "artists": [{"name": "Artist"}],
        }
    }
