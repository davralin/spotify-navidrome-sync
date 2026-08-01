from __future__ import annotations

import httpx

from spotify_navidrome_sync.navidrome import NavidromeClient


def test_search_songs_parses_isrc_lists_and_separated_values() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/search3.view")
        return httpx.Response(
            200,
            json={
                "subsonic-response": {
                    "status": "ok",
                    "searchResult3": {
                        "song": [
                            {
                                "id": "song",
                                "title": "Song",
                                "artist": "Artist",
                                "duration": 120,
                                "suffix": "flac",
                                "isrc": ["NO1234567890; NO2345678901", "NO3456789012"],
                            }
                        ]
                    },
                }
            },
        )

    client = NavidromeClient(
        "https://navidrome.example.org",
        "user",
        "password",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )

    songs = client.search_songs("Artist Song")

    assert songs[0].isrcs == ("NO1234567890", "NO2345678901", "NO3456789012")


def test_replace_playlist_creates_playlist_with_repeated_song_ids() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/getPlaylists.view"):
            return httpx.Response(
                200,
                json={"subsonic-response": {"status": "ok", "playlists": {"playlist": []}}},
            )
        return httpx.Response(
            200,
            json={"subsonic-response": {"status": "ok", "playlist": {"id": "created"}}},
        )

    client = NavidromeClient(
        "https://navidrome.example.org",
        "user",
        "password",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )

    playlist_id = client.replace_playlist("Spotify Sync Test", ("song-1", "song-2"))

    assert playlist_id == "created"
    create_body = requests[-1].content.decode()
    assert "name=Spotify+Sync+Test" in create_body
    assert create_body.count("songId=") == 2
    assert "songId=song-1" in create_body
    assert "songId=song-2" in create_body


def test_replace_playlist_updates_existing_playlist() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/getPlaylists.view"):
            return httpx.Response(
                200,
                json={
                    "subsonic-response": {
                        "status": "ok",
                        "playlists": {
                            "playlist": [{"id": "existing", "name": "Spotify Sync Test"}]
                        },
                    }
                },
            )
        return httpx.Response(200, json={"subsonic-response": {"status": "ok"}})

    client = NavidromeClient(
        "https://navidrome.example.org/rest",
        "user",
        "password",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )

    playlist_id = client.replace_playlist("Spotify Sync Test", ("song-1",))

    assert playlist_id == "existing"
    update_body = requests[-1].content.decode()
    assert "playlistId=existing" in update_body
    assert "songId=song-1" in update_body
