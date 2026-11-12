"""The dashboard's HTTP interface, driven against a real server on a free port."""
import base64
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest
import uvicorn

from clip_it.web.app import create_app
from test_clips import candidate, config, vod_folder


def serve(app):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.02)
    return server, f"http://127.0.0.1:{port}"


def call(url, method="GET", body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as err:
        return err.code, err.read(), err.headers


@pytest.fixture
def site(tmp_path):
    folder = vod_folder(tmp_path, candidate())
    (folder / "clip_001000.mp4").write_bytes(b"0123456789" * 100)
    server, base = serve(create_app(config(), root=tmp_path / "vods"))
    yield base
    server.should_exit = True


def test_the_page_and_the_clip_list_are_served(site):
    status, page, _ = call(site + "/")
    assert status == 200 and b"<html" in page

    status, body, _ = call(site + "/api/clips")
    (vod,) = json.loads(body)["vods"]
    assert vod["vod"] == "123" and vod["candidates"][0]["hook"] == "Der Chat lacht"


def test_an_edit_is_saved(site):
    status, body, _ = call(site + "/api/clips/123/1000", "PATCH", {"status": "approved"})

    assert status == 200 and json.loads(body)["status"] == "approved"


def test_an_invalid_edit_is_refused_with_the_reason(site):
    status, body, _ = call(site + "/api/clips/123/1000", "PATCH", {"layout": "sideways"})

    assert status == 400 and "layout" in json.loads(body)["detail"]


def test_an_unknown_clip_is_not_found(site):
    assert call(site + "/api/clips/123/7", "PATCH", {"status": "approved"})[0] == 404
    assert call(site + "/api/clips/999/1000", "PATCH", {"status": "approved"})[0] == 404


@pytest.mark.parametrize("path", ["/media/123/candidates.json", "/media/123/..%2F..%2Fconfig.yaml",
                                  "/media/x/clip_001000.mp4"])
def test_only_clip_and_excerpt_videos_can_be_fetched(site, path):
    assert call(site + path)[0] in (400, 404)


def test_videos_can_be_fetched_in_parts_so_the_player_can_seek(site):
    status, body, headers = call(site + "/media/123/clip_001000.mp4", headers={"Range": "bytes=10-19"})

    assert status == 206 and body == b"0123456789"


def test_with_a_password_every_page_asks_for_it(tmp_path):
    vod_folder(tmp_path, candidate())
    server, base = serve(create_app(config(), root=tmp_path / "vods", password="geheim"))
    try:
        assert call(base + "/api/clips")[0] == 401
        wrong = base64.b64encode(b"x:falsch").decode()
        assert call(base + "/api/clips", headers={"Authorization": f"Basic {wrong}"})[0] == 401
        right = base64.b64encode(b"x:geheim").decode()
        assert call(base + "/api/clips", headers={"Authorization": f"Basic {right}"})[0] == 200
    finally:
        server.should_exit = True


def test_publishing_without_permission_answers_with_the_reason(site):
    status, body, _ = call(site + "/api/clips/123/1000/publish", "POST", {"when": "slot"})

    assert status == 409 and "permission" in json.loads(body)["detail"]


def test_the_schedule_names_the_next_free_slot(site):
    status, body, _ = call(site + "/api/schedule")

    data = json.loads(body)
    assert status == 200 and data["next_slot"] and data["upcoming"] == []
