"""From a VOD to ranked excerpts on disk."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .config import detect_settings
from .detect import detect, read_chat
from .render import render
from .signals import loudness, rank
from .twitch import download_audio, download_chat, download_excerpt, vod_id

DATA = Path("data/vods")


def process(reference: str, cfg: dict, streamer: str | None = None, say=print) -> dict:
    """Find the highlights of one VOD, download their excerpts and render the clips.

    Everything lands in data/vods/<id>/; the returned summary is also written
    there as candidates.json.
    """
    vod = vod_id(reference)
    folder = DATA / vod
    chat_path = folder / "chat.json"
    if not chat_path.exists():
        say("Downloading the chat log ...")
        download_chat(vod, chat_path)
    chat = read_chat(chat_path)
    login = (streamer or chat.streamer).lower()
    settings = detect_settings(cfg, login)

    highlights = detect(chat, settings)
    say(f"{len(highlights)} highlight(s) in the chat")
    levels, offset = None, 0
    if highlights:
        offset, end = int(min(h.start_s for h in highlights)), int(max(h.end_s for h in highlights)) + 1
        cache = folder / "loudness.json"  # so that a re-run does not download the audio again
        saved = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else None
        if saved and saved["offset"] <= offset and saved["offset"] + len(saved["levels"]) >= end:
            levels, offset = saved["levels"], saved["offset"]
        else:
            audio = folder / "audio.m4a"
            say("Downloading the audio track ...")
            download_audio(vod, audio, offset, end)
            levels = loudness(audio)
            audio.unlink()  # only needed for this measurement
            cache.write_text(json.dumps({"offset": offset, "levels": levels}), encoding="utf-8")
    ranked, dropped = rank(highlights, levels, {**cfg["signals"], "top_n": settings["top_n"]}, offset)

    reserve = cfg["clip"]["reserve_s"]
    candidates = []
    for number, h in enumerate(ranked, 1):
        # Files are named after the second of the stream, so a re-run finds them again.
        start, end = max(0.0, h.start_s - reserve), min(chat.duration, h.end_s + reserve)
        file = folder / f"excerpt_{h.spike_s:06d}.mp4"
        if not file.exists():
            say(f"Downloading excerpt {number} of {len(ranked)} ...")
            download_excerpt(vod, file, start, end)
        clip = folder / f"clip_{h.spike_s:06d}.mp4"
        say(f"Rendering clip {number} of {len(ranked)} ...")
        render(file, clip, h.start_s - start, h.end_s - start, cfg, login)
        candidates.append(
            {"rank": number, **asdict(h), "file": file.name, "file_start_s": start, "file_end_s": end,
             "clip": clip.name}
        )

    summary = {
        "vod": vod,
        "streamer": login,
        "title": chat.title,
        "folder": str(folder),
        "candidates": candidates,
        "dropped_muted": [asdict(h) for h in dropped],
    }
    (folder / "candidates.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
