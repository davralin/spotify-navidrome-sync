from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast

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


def test_scan_api_uses_real_http_requests() -> None:
    requests: list[tuple[str, str]] = []
    scan_status_responses = [True, False]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            requests.append((self.path, body))
            if self.path.endswith("/startScan.view"):
                self._send_json({"subsonic-response": {"status": "ok"}})
                return
            if self.path.endswith("/getScanStatus.view"):
                scanning = scan_status_responses.pop(0)
                self._send_json(
                    {
                        "subsonic-response": {
                            "status": "ok",
                            "scanStatus": {"scanning": scanning, "count": 10},
                        }
                    }
                )
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        host, port = cast(tuple[str, int], server.server_address)
        client = NavidromeClient(f"http://{host}:{port}", "user", "password")

        client.start_scan()
        client.wait_for_scan_completion(timeout_seconds=5, poll_seconds=0.01)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    paths = [path for path, _body in requests]
    assert paths == ["/rest/startScan.view", "/rest/getScanStatus.view", "/rest/getScanStatus.view"]
    assert all("u=user" in body for _path, body in requests)
