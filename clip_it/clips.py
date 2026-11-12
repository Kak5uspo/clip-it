"""Clip records (data/vods/<id>/candidates.json): loading, validated edits, rendering one clip.

All times in a record are seconds of the stream. Words are stored as
[start, end, text] so subtitles can be corrected and re-rendered without
transcribing again.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import transcribe, youtube
from .render import hook_position, layout_for, render
from .signals import loudest_moment
from .subtitles import Word, build_ass

ROOT = Path("data/vods")
STATUSES = ("new", "approved", "rejected")
_LOCK = threading.Lock()  # ponytail: one lock for all files; fine for one person and one process


class InvalidChange(ValueError):
    """An edit that would leave a clip record in a broken state."""


def folder_for(vod: str, root: Path = ROOT) -> Path:
    if not re.fullmatch(r"\d+", vod):
        raise InvalidChange("a VOD id is a number")
    return root / vod


def load(folder: Path) -> dict:
    return json.loads((folder / "candidates.json").read_text(encoding="utf-8"))


def save(folder: Path, data: dict) -> None:
    """Write via a temporary file, so a crash never leaves half a file behind."""
    tmp = folder / "candidates.json.tmp"
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, folder / "candidates.json")


def all_vods(root: Path = ROOT) -> list[dict]:
    """Every processed VOD, newest folder first."""
    files = sorted(root.glob("*/candidates.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [json.loads(p.read_text(encoding="utf-8")) for p in files]


def find(data: dict, spike_s: int) -> dict:
    for record in data["candidates"]:
        if record["spike_s"] == spike_s:
            return record
    raise KeyError(f"no clip at second {spike_s}")


def _text(value, field: str, limit: int) -> str:
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise InvalidChange(f"{field} must be text of at most {limit} characters")
    return value.strip()


def _apply(record: dict, changes: dict, cfg: dict) -> None:
    for field, value in changes.items():
        if field in ("hook", "title"):
            record[field] = _text(value, field, 80 if field == "hook" else 100)
        elif field == "hashtags":
            if not isinstance(value, list) or len(value) > 10 or not all(
                isinstance(t, str) and re.fullmatch(r"#\w{1,50}", t) for t in value
            ):
                raise InvalidChange("hashtags must be up to 10 words starting with #")
            record[field] = value
        elif field == "words":
            if not isinstance(value, list) or len(value) != len(record["words"]):
                raise InvalidChange("words: corrections must keep the number of words")
            record["words"] = [[w[0], w[1], _text(t, "a word", 40)] for w, t in zip(record["words"], value)]
        elif field == "layout":
            if value not in (None, "split", "blur"):
                raise InvalidChange("layout must be split or blur")
            record[field] = value
        elif field in ("zoom", "tiktok_posted"):
            if not isinstance(value, bool):
                raise InvalidChange(f"{field} must be true or false")
            record[field] = value
        elif field == "status":
            if value not in STATUSES:
                raise InvalidChange(f"status must be one of {', '.join(STATUSES)}")
            record[field] = value
        elif field in ("clip_start_s", "clip_end_s"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise InvalidChange(f"{field} must be a number")
            record[field] = round(float(value), 2)
        else:
            raise InvalidChange(f"{field} cannot be changed")
    start, end = record["clip_start_s"], record["clip_end_s"]
    if start < record["file_start_s"] or end > record["file_end_s"]:
        raise InvalidChange("start and end must lie inside the downloaded excerpt")
    if end - start < 3:
        raise InvalidChange("the end must be at least 3 seconds after the start")
    if end - start > cfg["clip"]["hard_max_s"]:
        raise InvalidChange(f"a clip may be at most {cfg['clip']['hard_max_s']} seconds long")


def update(folder: Path, spike_s: int, changes: dict, cfg: dict) -> dict:
    """Apply validated edits to one clip and save them. Nothing is saved if one edit is invalid."""
    with _LOCK:
        data = load(folder)
        record = find(data, spike_s)
        edited = json.loads(json.dumps(record))
        _apply(edited, changes, cfg)
        record.clear()
        record.update(edited)
        save(folder, data)
        return record


def _cover_words(folder: Path, record: dict, language: str, model: str) -> None:
    """Transcribe the parts of the clip that lie outside the transcript, e.g. after re-trimming."""
    if not transcribe.available():
        return
    excerpt, offset = folder / record["file"], record["file_start_s"]
    start, end = record["clip_start_s"], record["clip_end_s"]
    if start < record["words_from_s"]:
        new = transcribe.transcribe(excerpt, start - offset, record["words_from_s"] - offset, language, model)
        record["words"] = [[w.start + offset, w.end + offset, w.text] for w in new] + record["words"]
        record["words_from_s"] = start
    if end > record["words_to_s"]:
        new = transcribe.transcribe(excerpt, record["words_to_s"] - offset, end - offset, language, model)
        record["words"] += [[w.start + offset, w.end + offset, w.text] for w in new]
        record["words_to_s"] = end


def render_clip(folder: Path, record: dict, cfg: dict, login: str) -> None:
    """Render one clip from its record: trim, layout, words, hook and zoom as stored there."""
    streamer = cfg["streamers"][login]
    if cfg["subtitles"]["enabled"]:
        _cover_words(folder, record, streamer["language"], cfg["subtitles"]["model"])
    start, end, offset = record["clip_start_s"], record["clip_end_s"], record["file_start_s"]
    spoken = [Word(s - start, e - start, t) for s, e, t in record["words"] if s >= start and e <= end]
    layout = record.get("layout") or layout_for(streamer)
    clip = folder / record["clip"]
    ass = clip.with_suffix(".ass")
    ass.write_text(
        build_ass(spoken, cfg["subtitles"], streamer["language"], hook=record["hook"],
                  hook_y=hook_position(layout, streamer, cfg["render"])),
        encoding="utf-8",
    )
    zoom_at = None
    cache = folder / "loudness.json"
    if record.get("zoom", True) and cache.exists():
        saved = json.loads(cache.read_text(encoding="utf-8"))
        loud = loudest_moment(saved["levels"], start, end, saved["offset"], cfg["render"]["zoom"]["min_rise_db"])
        zoom_at = None if loud is None else loud - start
    render(folder / record["file"], clip, start - offset, end - offset, cfg, login, layout=layout,
           ass=ass, zoom_at=zoom_at)


def publish(folder: Path, spike_s: int, when: str, cfg: dict, now: datetime | None = None) -> dict:
    """Approve a clip and upload it to YouTube.

    `when` is "slot" (the next free posting slot), "now", or a local date and time
    such as "2026-11-19T18:00". Raises youtube.UploadRefused with the reason if the
    upload is not possible; the record is only changed after a successful upload.
    """
    settings = cfg["publish"]["youtube"]
    zone = ZoneInfo(settings["timezone"])
    now = now or datetime.now(timezone.utc)
    with _LOCK:
        data = load(folder)
        record = find(data, spike_s)
        login = data["streamer"]
        streamer = cfg["streamers"][login]
        if record.get("youtube_id"):
            raise youtube.UploadRefused("This clip is already on YouTube.")
        youtube.check_permission(streamer, login, youtube.PERMISSIONS)
        if when == "now":
            publish_at = None
        elif when == "slot":
            taken = [datetime.fromisoformat(c["publish_at"]) for vod in all_vods(folder.parent)
                     for c in vod["candidates"] if c.get("publish_at")]
            publish_at = youtube.next_slot(now, settings["slots"], settings["timezone"], taken)
        else:
            try:
                publish_at = datetime.fromisoformat(when)
            except ValueError:
                raise youtube.UploadRefused(f"Not a date and time: {when}") from None
            publish_at = publish_at if publish_at.tzinfo else publish_at.replace(tzinfo=zone)
            if publish_at <= now:
                raise youtube.UploadRefused("That time is in the past.")
    # Uploading takes a while; the lock is not held meanwhile, so the dashboard stays usable.
    # ponytail: two approvals in the same second could pick the same slot; fine for one person.
    video_id = youtube.upload(
        youtube.service(), folder / record["clip"], youtube.video_title(record, streamer, settings["title"]),
        youtube.description(record, login, settings["description"]),
        [t.lstrip("#") for t in record["hashtags"]], streamer["language"], publish_at,
    )
    with _LOCK:
        data = load(folder)
        record = find(data, spike_s)
        record.update(status="approved", youtube_id=video_id,
                      publish_at=(publish_at or now).astimezone(timezone.utc).isoformat())
        save(folder, data)
        return record
