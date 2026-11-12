"""Render vertical clips with ffmpeg."""
from __future__ import annotations

import functools
import subprocess
from pathlib import Path

from .twitch import ToolError, find_tool

_ZOOM_RAMP_S = 0.15  # seconds to zoom in and back out
FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Montserrat-Black.ttf"

# H.264 encoders with their quality settings, in the order "auto" tries them.
# Only h264_amf and libx264 have been tested; the others follow the ffmpeg documentation.
# Measured on a 28 s gameplay clip (laptop, integrated AMD GPU), SSIM against a near-lossless render:
#   libx264 crf 20: 8.0 s, 35 MB, 0.987    h264_amf qp 25/27: 6.0 s, 41 MB, 0.986
ENCODERS = {
    "h264_nvenc": ["-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"],
    "h264_amf": ["-quality", "quality", "-rc", "cqp", "-qp_i", "25", "-qp_p", "27"],
    "h264_qsv": ["-global_quality", "21"],
    "h264_videotoolbox": ["-q:v", "60"],
    "libx264": ["-preset", "veryfast", "-crf", "20"],
}


def _ffmpeg(*args: str) -> subprocess.CompletedProcess:
    ffmpeg = find_tool("ffmpeg")
    if not ffmpeg:
        raise ToolError("ffmpeg not found")
    return subprocess.run(
        [ffmpeg, "-v", "error", "-y", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


@functools.cache
def pick_encoder(preference: str = "auto") -> str:
    """The H.264 encoder to use. "auto" takes the first one that passes a short test encode."""
    if preference != "auto":
        if preference not in ENCODERS:
            raise ToolError(f"Unknown encoder '{preference}'; use auto or one of: {', '.join(ENCODERS)}")
        return preference
    for name, quality in ENCODERS.items():
        test = _ffmpeg("-f", "lavfi", "-i", "color=s=1080x1920:r=60:d=0.5", "-c:v", name, *quality,
                       "-pix_fmt", "yuv420p", "-f", "null", "-")
        if test.returncode == 0:
            return name
    raise ToolError("ffmpeg has no working H.264 encoder")


def layout_for(streamer: dict) -> str:
    """The streamer's layout; "split" only works with both rectangles and otherwise becomes "blur"."""
    if streamer["layout"] == "split" and streamer["facecam"] and streamer["gameplay"]:
        return "split"
    return "blur"


def _escape(text: str) -> str:
    """Make a path or text safe inside a quoted ffmpeg filter option."""
    return text.replace("\\", "/").replace(":", "\\:").replace("'", "").replace("%", "\\%")


def _cam_height(streamer: dict, r: dict) -> int:
    return round(r["height"] * streamer["facecam_share"] / 2) * 2


def hook_position(layout: str, streamer: dict, r: dict) -> int:
    """Vertical centre of the hook banner: on the dividing line (split) or above the picture (blur)."""
    if layout == "split":
        return _cam_height(streamer, r)
    return (r["height"] - r["width"] * 9 // 16) // 2 - 70


def _graph(layout: str, streamer: dict, r: dict, login: str, ass: Path | None, zoom_at: float | None) -> str:
    w, h = r["width"], r["height"]
    if layout == "split":
        cam_h = _cam_height(streamer, r)
        parts = []
        for name, key, out_h in (("cam", "facecam", cam_h), ("game", "gameplay", h - cam_h)):
            rect = streamer[key]
            parts.append(
                f"crop=iw*{rect['w']}:ih*{rect['h']}:iw*{rect['x']}:ih*{rect['y']},"
                f"scale={w}:{out_h}:force_original_aspect_ratio=increase,crop={w}:{out_h}[{name}]"
            )
        graph = f"[0:v]split=2[a][b];[a]{parts[0]};[b]{parts[1]};[cam][game]vstack"
        credit_y = cam_h - 62
    else:
        # The background is blurred at a quarter of the size, which looks the same and is far cheaper.
        graph = (
            f"[0:v]split=2[a][b];"
            f"[a]scale={w // 4}:{h // 4}:force_original_aspect_ratio=increase,crop={w // 4}:{h // 4},"
            f"boxblur=6:2,scale={w}:{h}[bg];"
            f"[b]scale={w}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
        credit_y = (h + w * 9 // 16) // 2 + 20  # just below a 16:9 picture
    graph += f",fps={r['fps']},setsar=1"
    if zoom_at is not None and r["zoom"]["enabled"]:
        # Ease in over _ZOOM_RAMP_S from zoom_at, hold, ease back out; magnified around the centre.
        z, a, hold = r["zoom"]["factor"], zoom_at, r["zoom"]["hold_s"]
        k = f"clip(min((it-{a:.3f})/{_ZOOM_RAMP_S},({a + 2 * _ZOOM_RAMP_S + hold:.3f}-it)/{_ZOOM_RAMP_S}),0,1)"
        graph += (
            f",zoompan=z='1+{z - 1:.4f}*{k}':d=1:x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'"
            f":s={w}x{h}:fps={r['fps']}"
        )
    credit = r["credit"].format(login=login)
    if credit:
        opacity = r["credit_opacity"]
        graph += (
            f",drawtext=fontfile='{_escape(str(FONT))}':text='{_escape(credit)}':fontsize=40"
            f":fontcolor=white@{opacity}:borderw=3:bordercolor=black@{opacity}:x=36:y={credit_y}"
        )
    if ass:
        graph += f",subtitles=filename='{_escape(str(ass.resolve()))}':fontsdir='{_escape(str(FONT.parent))}'"
    return graph + "[v]"


def render(
    source: Path, out: Path, start: float, end: float, cfg: dict, login: str,
    layout: str | None = None, ass: Path | None = None, zoom_at: float | None = None,
) -> None:
    """Render the part of `source` from `start` to `end` (seconds) as a vertical clip.

    `ass` is an optional subtitle file whose times count from the start of the clip;
    `zoom_at` is the second of the clip at which the picture briefly zooms in.
    """
    r, streamer = cfg["render"], cfg["streamers"][login]
    encoder = pick_encoder(r["encoder"])
    out.parent.mkdir(parents=True, exist_ok=True)
    result = _ffmpeg(
        "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(source),
        "-filter_complex", _graph(layout or layout_for(streamer), streamer, r, login, ass, zoom_at),
        "-map", "[v]", "-map", "0:a:0",
        # ponytail: single-pass loudnorm; measure first and run it twice if clips miss the target audibly.
        "-af", f"loudnorm=I={r['loudness_lufs']}:TP=-1.5:LRA=11", "-ar", "48000",
        "-c:v", encoder, *ENCODERS[encoder], "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", f"{r['audio_kbps']}k", "-movflags", "+faststart", str(out),
    )
    if result.returncode != 0:
        raise ToolError(f"ffmpeg could not render {out.name}: {result.stderr.strip()[-600:]}")


def layout_check(source: Path, out: Path, streamer: dict, at: float = 0.0) -> None:
    """Save one frame with a 10 % grid and the streamer's rectangles drawn in."""
    draw = "drawgrid=w=iw/10:h=ih/10:t=2:c=white@0.5"
    for key, color in (("gameplay", "cyan"), ("facecam", "yellow")):
        rect = streamer[key]
        if rect:
            draw += (
                f",drawbox=x=iw*{rect['x']}:y=ih*{rect['y']}:w=iw*{rect['w']}:h=ih*{rect['h']}"
                f":color={color}:t=6"
            )
    out.parent.mkdir(parents=True, exist_ok=True)
    result = _ffmpeg("-ss", f"{at:.3f}", "-i", str(source), "-frames:v", "1", "-vf", draw, str(out))
    if result.returncode != 0:
        raise ToolError(f"ffmpeg could not draw the layout check: {result.stderr.strip()[-600:]}")
