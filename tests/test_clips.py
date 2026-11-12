"""Clip records: edits from the dashboard and re-rendering one clip."""
import json
import shutil
import subprocess

import pytest

from clip_it import clips
from clip_it.config import build_config

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def config():
    return build_config({"render": {"encoder": "libx264"}, "suggest": {"provider": "rules"},
                         "streamers": {"test": {"language": "de"}}})


def candidate(**changes):
    record = {
        "spike_s": 1000, "file": "excerpt_001000.mp4", "file_start_s": 960.0, "file_end_s": 1068.0,
        "clip_start_s": 975.0, "clip_end_s": 1003.0, "clip": "clip_001000.mp4",
        "hooks": ["Der Chat lacht", "Zweiter", "Dritter"], "hook": "Der Chat lacht",
        "title": "Titel", "hashtags": ["#gta"], "label": "laugh", "game": None,
        "words": [[976.0, 976.5, "das"], [976.5, 977.0, "war"], [977.0, 977.6, "irre"]],
        "words_from_s": 970.0, "words_to_s": 1010.0,
        "layout": None, "zoom": True, "status": "new", "tiktok_posted": False,
    }
    record.update(changes)
    return record


def vod_folder(tmp_path, *records):
    folder = tmp_path / "vods" / "123"
    folder.mkdir(parents=True)
    data = {"vod": "123", "streamer": "test", "title": "Stream", "candidates": list(records), "dropped_muted": []}
    (folder / "candidates.json").write_text(json.dumps(data), encoding="utf-8")
    return folder


def test_texts_status_and_options_can_be_changed(tmp_path):
    folder = vod_folder(tmp_path, candidate())

    updated = clips.update(folder, 1000, {
        "hook": "Er drückt F", "title": "Neuer Titel", "hashtags": ["#gta5", "#fail"],
        "layout": "blur", "zoom": False, "status": "approved", "tiktok_posted": True,
    }, config())

    assert updated["hook"] == "Er drückt F" and updated["status"] == "approved"
    saved = json.loads((folder / "candidates.json").read_text(encoding="utf-8"))["candidates"][0]
    assert saved["layout"] == "blur" and saved["zoom"] is False and saved["tiktok_posted"] is True


def test_corrected_words_keep_their_timing(tmp_path):
    folder = vod_folder(tmp_path, candidate())

    updated = clips.update(folder, 1000, {"words": ["das", "wahr", "irre"]}, config())

    assert updated["words"][1] == [976.5, 977.0, "wahr"]


@pytest.mark.parametrize("changes, message", [
    ({"clip_start_s": 950.0}, "excerpt"),          # before the downloaded excerpt
    ({"clip_end_s": 1070.0}, "excerpt"),           # after it
    ({"clip_start_s": 975.0, "clip_end_s": 1040.0}, "59"),  # longer than a Short may be
    ({"clip_start_s": 990.0, "clip_end_s": 989.0}, "end"),  # end before start
    ({"status": "published"}, "status"),
    ({"layout": "sideways"}, "layout"),
    ({"words": ["nur", "zwei"]}, "words"),          # corrections must keep the word count
    ({"hashtags": ["gta"]}, "#"),
    ({"hook": "x" * 81}, "hook"),
    ({"file": "../../secret"}, "file"),            # not editable at all
])
def test_invalid_changes_are_rejected_and_nothing_is_saved(tmp_path, changes, message):
    folder = vod_folder(tmp_path, candidate())
    before = (folder / "candidates.json").read_text(encoding="utf-8")

    with pytest.raises(clips.InvalidChange, match=message):
        clips.update(folder, 1000, changes, config())

    assert (folder / "candidates.json").read_text(encoding="utf-8") == before


def test_unknown_clip_is_reported(tmp_path):
    folder = vod_folder(tmp_path, candidate())

    with pytest.raises(KeyError):
        clips.update(folder, 999, {"hook": "x"}, config())


def test_vod_ids_that_are_not_numbers_are_rejected(tmp_path):
    with pytest.raises(clips.InvalidChange):
        clips.folder_for("../123", root=tmp_path)


@needs_ffmpeg
def test_render_uses_the_edited_hook_words_and_trim(tmp_path):
    record = candidate(hook="Mein Hook", clip_start_s=975.5, clip_end_s=979.0)
    record["words"][1][2] = "wahr"
    folder = vod_folder(tmp_path, record)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=1920x1080:r=60:d=30",
         "-f", "lavfi", "-i", "sine=duration=30", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(folder / "excerpt_001000.mp4")],
        check=True,
    )

    clips.render_clip(folder, record, config(), "test")

    ass = (folder / "clip_001000.ass").read_text(encoding="utf-8")
    assert "MEIN HOOK" in ass and "WAHR" in ass and "WAR " not in ass
    duration = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
         str(folder / "clip_001000.mp4")], capture_output=True, text=True, check=True,
    ).stdout)
    assert duration == pytest.approx(3.5, abs=0.15)
