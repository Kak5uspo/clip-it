"""The review dashboard: a JSON API over the clip records plus one HTML page."""
from __future__ import annotations

import base64
import re
import secrets
import threading
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from .. import clips
from ..render import layout_for

PAGE = Path(__file__).with_name("index.html")
_RENDER_LOCK = threading.Lock()  # one ffmpeg at a time; the laptop has no spare cores for two


def create_app(cfg: dict, root: Path = clips.ROOT, password: str | None = None) -> FastAPI:
    app = FastAPI(title="ClipIt", docs_url=None, redoc_url=None, openapi_url=None)

    if password:
        expected = password.encode()

        @app.middleware("http")
        async def require_password(request: Request, call_next):
            header = request.headers.get("authorization", "")
            given = b""
            if header.startswith("Basic "):
                try:
                    given = base64.b64decode(header[6:]).partition(b":")[2]
                except ValueError:
                    pass
            if not secrets.compare_digest(given, expected):
                return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="ClipIt"'})
            return await call_next(request)

    def folder(vod: str) -> Path:
        try:
            path = clips.folder_for(vod, root)
        except clips.InvalidChange:
            raise HTTPException(404, "no such VOD") from None
        if not (path / "candidates.json").exists():
            raise HTTPException(404, "no such VOD")
        return path

    def record(vod: str, spike_s: int) -> tuple[Path, dict]:
        path = folder(vod)
        try:
            return path, clips.find(clips.load(path), spike_s)
        except KeyError:
            raise HTTPException(404, "no such clip") from None

    @app.get("/")
    def page():
        return FileResponse(PAGE)

    @app.get("/api/clips")
    def list_clips():
        vods = clips.all_vods(root)
        for vod in vods:  # the layout a clip gets unless it sets its own
            streamer = cfg["streamers"].get(vod["streamer"])
            vod["layout"] = layout_for(streamer) if streamer else "blur"
        return {"vods": vods}

    @app.patch("/api/clips/{vod}/{spike_s}")
    def edit(vod: str, spike_s: int, changes: dict = Body(...)):
        path, _ = record(vod, spike_s)
        try:
            return clips.update(path, spike_s, changes, cfg)
        except clips.InvalidChange as err:
            raise HTTPException(400, str(err)) from None

    @app.post("/api/clips/{vod}/{spike_s}/render")
    def rerender(vod: str, spike_s: int):
        # A plain function: FastAPI runs it in a worker thread, so the page stays responsive.
        path, _ = record(vod, spike_s)
        with _RENDER_LOCK:
            data = clips.load(path)
            current = clips.find(data, spike_s)
            clips.render_clip(path, current, cfg, data["streamer"])
            clips.save(path, data)  # rendering may have added words after re-trimming
        return current

    @app.get("/media/{vod}/{name}")
    def media(vod: str, name: str, download: bool = False):
        if not re.fullmatch(r"(clip|excerpt)_\d{6}\.mp4", name):
            raise HTTPException(404, "not a video")
        path = folder(vod) / name
        if not path.exists():
            raise HTTPException(404, "not a video")
        return FileResponse(path, media_type="video/mp4", filename=name if download else None,
                            headers={"Cache-Control": "no-cache"})

    @app.exception_handler(ValueError)
    async def bad_value(request: Request, err: ValueError):
        return JSONResponse({"detail": str(err)}, status_code=400)

    return app
