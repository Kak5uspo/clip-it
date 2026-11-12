"""Rendering: both layouts, checked on a synthetic test video."""
import json
import re
import shutil
import subprocess

import pytest

from clip_it.config import ConfigError, build_config
from clip_it.render import hook_position, layout_check, layout_for, render
from clip_it.subtitles import Word, build_ass

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")

# Where the test video keeps its "facecam" (red) and "gameplay" (blue); the rest is green.
FACECAM = {"x": 0.75, "y": 0.2, "w": 0.25, "h": 0.3}
GAMEPLAY = {"x": 0.25, "y": 0.0, "w": 0.5, "h": 1.0}


def config(**streamer):
    return build_config({"render": {"encoder": "libx264"}, "streamers": {"test": streamer}})


def probe(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    streams = {s["codec_type"]: s for s in data["streams"]}
    return streams, float(data["format"].get("duration", 0))  # a still image has no duration


def pixel(video, x, y, at=1.0):
    """RGB colour of one pixel of the frame at `at` seconds."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(video), "-frames:v", "1",
         "-vf", f"crop=2:2:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout
    return tuple(raw[:3])


def is_red(rgb):
    return rgb[0] > 150 and rgb[1] < 90 and rgb[2] < 90


def is_blue(rgb):
    return rgb[2] > 150 and rgb[0] < 90 and rgb[1] < 90


def is_green(rgb):
    return rgb[1] > 90 and rgb[0] < 60 and rgb[2] < 60


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    """Six seconds of 1920x1080 at 60 fps with a quiet tone."""
    path = tmp_path_factory.mktemp("source") / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=green:s=1920x1080:r=60:d=6",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
         "-vf", "drawbox=x=480:y=0:w=960:h=1080:color=blue:t=fill,"
                "drawbox=x=1440:y=216:w=480:h=324:color=red:t=fill",
         "-af", "volume=0.05", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(path)],
        check=True,
    )
    return path


@pytest.fixture(scope="module")
def split_clip(source, tmp_path_factory):
    out = tmp_path_factory.mktemp("split") / "clip.mp4"
    render(source, out, 1.0, 5.0, config(layout="split", facecam=FACECAM, gameplay=GAMEPLAY), "test")
    return out


@pytest.fixture(scope="module")
def blur_clip(source, tmp_path_factory):
    out = tmp_path_factory.mktemp("blur") / "clip.mp4"
    render(source, out, 1.0, 5.0, config(), "test")
    return out


@needs_ffmpeg
def test_clip_has_the_shorts_format(split_clip):
    streams, duration = probe(split_clip)

    assert (streams["video"]["width"], streams["video"]["height"]) == (1080, 1920)
    assert streams["video"]["r_frame_rate"] == "60/1"
    assert streams["video"]["codec_name"] == "h264"
    assert streams["video"]["pix_fmt"] == "yuv420p"
    assert streams["audio"]["codec_name"] == "aac"
    assert duration == pytest.approx(4.0, abs=0.15)


@needs_ffmpeg
def test_clip_carries_its_index_at_the_front_so_it_can_start_playing_at_once(split_clip):
    data = split_clip.read_bytes()

    assert data.index(b"moov") < data.index(b"mdat")


@needs_ffmpeg
def test_split_puts_the_facecam_on_top_and_the_gameplay_below(split_clip):
    assert is_red(pixel(split_clip, 540, 300))  # upper 38 % of the picture
    assert is_blue(pixel(split_clip, 540, 1400))


@needs_ffmpeg
def test_blur_shows_the_whole_frame_in_the_middle_over_a_filled_background(blur_clip):
    assert is_blue(pixel(blur_clip, 540, 960))  # centre of the source
    assert is_green(pixel(blur_clip, 60, 960))  # its left edge is still there
    assert sum(pixel(blur_clip, 540, 200)) > 60  # above the frame: blurred picture, not black


@needs_ffmpeg
def test_loudness_is_brought_to_the_target(split_clip):
    report = subprocess.run(
        ["ffmpeg", "-i", str(split_clip), "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    integrated = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", report)[-1])

    assert integrated == pytest.approx(-14.0, abs=2.0)  # the source tone is far quieter


def count_pixels(video, at, x, y, w, h, matches):
    """How many pixels of a region of one frame satisfy `matches(r, g, b)`."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(video), "-frames:v", "1",
         "-vf", f"crop={w}:{h}:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout
    return sum(1 for i in range(0, len(raw), 3) if matches(*raw[i : i + 3]))


def white(r, g, b):
    return min(r, g, b) > 200


def yellow(r, g, b):
    return r > 200 and g > 180 and b < 90


@needs_ffmpeg
def test_subtitles_and_hook_are_burned_into_the_picture(source, tmp_path):
    cfg = config(layout="split", facecam=FACECAM, gameplay=GAMEPLAY)
    streamer = cfg["streamers"]["test"]
    ass = tmp_path / "clip.ass"
    ass.write_text(
        build_ass([Word(2.5, 3.0, "hallo"), Word(3.0, 3.5, "welt")], cfg["subtitles"], hook="Schau mal",
                  hook_y=hook_position("split", streamer, cfg["render"])),
        encoding="utf-8",
    )
    out = tmp_path / "clip.mp4"

    render(source, out, 1.0, 5.0, cfg, "test", ass=ass)

    subtitle_area = (140, 1207, 800, 120)  # around 66 % of the height
    # While "hallo" is spoken it is yellow and "welt" waits in white; before that the area is empty.
    assert count_pixels(out, 2.75, *subtitle_area, yellow) > 300
    assert count_pixels(out, 2.75, *subtitle_area, white) > 300
    assert count_pixels(out, 1.0, *subtitle_area, white) == 0
    # The hook is a yellow box on the dividing line during the first seconds only.
    hook_area = (140, 680, 800, 100)
    assert count_pixels(out, 1.0, *hook_area, yellow) > 3000
    assert count_pixels(out, 3.5, *hook_area, yellow) == 0


@needs_ffmpeg
def test_the_picture_zooms_in_at_the_loud_moment_and_back_out(source, tmp_path):
    out = tmp_path / "zoom.mp4"

    render(source, out, 0.0, 5.0, config(layout="split", facecam=FACECAM, gameplay=GAMEPLAY), "test", zoom_at=2.0)

    # Just above the dividing line the facecam (red) shows; zoomed in, the picture is
    # magnified around its centre and the gameplay (blue) moves up into that spot.
    assert is_red(pixel(out, 540, 715, at=1.0))
    assert is_blue(pixel(out, 540, 715, at=2.6))
    assert is_red(pixel(out, 540, 715, at=4.5))


@needs_ffmpeg
def test_layout_check_draws_the_rectangles_onto_a_frame(source, tmp_path):
    out = tmp_path / "check.png"
    streamer = config(layout="split", facecam=FACECAM, gameplay=GAMEPLAY)["streamers"]["test"]

    layout_check(source, out, streamer)

    streams, _ = probe(out)
    assert (streams["video"]["width"], streams["video"]["height"]) == (1920, 1080)
    r, g, b = pixel(out, 1442, 378, at=0)  # on the left border of the facecam rectangle
    assert r > 180 and g > 180 and b < 100  # yellow


def test_split_needs_both_rectangles_and_otherwise_falls_back_to_blur():
    with_rectangles = config(layout="split", facecam=FACECAM, gameplay=GAMEPLAY)["streamers"]["test"]
    without = config(layout="split")["streamers"]["test"]

    assert layout_for(with_rectangles) == "split"
    assert layout_for(without) == "blur"


def test_a_rectangle_outside_the_picture_is_rejected():
    with pytest.raises(ConfigError, match="streamers.test.facecam"):
        config(facecam={"x": 0.8, "y": 0.2, "w": 0.5, "h": 0.3})


def test_an_unknown_layout_is_rejected():
    with pytest.raises(ConfigError, match="streamers.test.layout"):
        config(layout="sideways")
