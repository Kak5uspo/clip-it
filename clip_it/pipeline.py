"""From a VOD to ranked excerpts on disk."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from . import clips, transcribe
from .config import detect_settings
from .detect import detect, read_chat
from .edit import fine_cut
from .signals import loudness, rank
from .suggest import suggest
from .twitch import download_audio, download_chat, download_excerpt, vod_id

DATA = Path("data/vods")
_LISTEN_S = 15  # how far beyond the rough window the transcript reaches, so the fine cut has room


def process(reference: str, cfg: dict, streamer: str | None = None, say=print, redo: bool = False) -> dict:
    """Find the highlights of one VOD, download their excerpts and render the clips.

    Everything lands in data/vods/<id>/; the returned summary is also written
    there as candidates.json. Clips an earlier run made are kept with their edits
    and status, unless `redo` is set.
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
    streamer = cfg["streamers"][login]

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
    previous = {}  # clips made by an earlier run keep their edits and status
    if (folder / "candidates.json").exists() and not redo:
        previous = {c["spike_s"]: c for c in clips.load(folder)["candidates"] if "words" in c}
    candidates = []
    for number, h in enumerate(ranked, 1):
        if h.spike_s in previous:
            candidates.append({**previous[h.spike_s], "rank": number})
            continue
        # Files are named after the second of the stream, so a re-run finds them again.
        start, end = max(0.0, h.start_s - reserve), min(chat.duration, h.end_s + reserve)
        file = folder / f"excerpt_{h.spike_s:06d}.mp4"
        if not file.exists():
            say(f"Downloading excerpt {number} of {len(ranked)} ...")
            download_excerpt(vod, file, start, end)
        say(f"Cutting and rendering clip {number} of {len(ranked)} ...")
        # Transcript and fine cut work in seconds of the excerpt file.
        cut_start, cut_end, words = h.start_s - start, h.end_s - start, []
        heard_from, heard_to = cut_start, cut_end
        if cfg["subtitles"]["enabled"] and transcribe.available():
            heard_from, heard_to = max(0.0, cut_start - _LISTEN_S), min(end - start, cut_end + _LISTEN_S)
            words = transcribe.transcribe(file, heard_from, heard_to, streamer["language"], cfg["subtitles"]["model"])
            cut_start, cut_end = fine_cut(words, cut_start, cut_end, cfg["clip"], end - start)
        text = " ".join(w.text for w in words if w.start >= cut_start and w.end <= cut_end)
        suggestion = suggest(h.label, streamer["language"], text, streamer["display_name"], h.game, cfg["suggest"])
        record = {
            "rank": number, **asdict(h), "file": file.name, "file_start_s": start, "file_end_s": end,
            "clip": f"clip_{h.spike_s:06d}.mp4",
            "clip_start_s": round(start + cut_start, 2), "clip_end_s": round(start + cut_end, 2),
            **suggestion, "hook": suggestion["hooks"][0], "text": text,
            "words": [[round(start + w.start, 2), round(start + w.end, 2), w.text] for w in words],
            "words_from_s": round(start + heard_from, 2), "words_to_s": round(start + heard_to, 2),
            "layout": None, "zoom": True, "status": "new", "tiktok_posted": False,
        }
        clips.render_clip(folder, record, cfg, login)
        candidates.append(record)

    summary = {
        "vod": vod,
        "streamer": login,
        "title": chat.title,
        "folder": str(folder),
        "candidates": candidates,
        "dropped_muted": [asdict(h) for h in dropped],
    }
    clips.save(folder, summary)
    return summary
