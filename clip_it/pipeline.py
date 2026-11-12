"""From a VOD to ranked excerpts on disk."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from . import transcribe
from .config import detect_settings
from .detect import detect, read_chat
from .edit import fine_cut
from .render import hook_position, layout_for, render
from .signals import loudest_moment, loudness, rank
from .subtitles import Word, build_ass
from .suggest import suggest
from .twitch import download_audio, download_chat, download_excerpt, vod_id

DATA = Path("data/vods")
_LISTEN_S = 15  # how far beyond the rough window the transcript reaches, so the fine cut has room


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
    candidates = []
    for number, h in enumerate(ranked, 1):
        # Files are named after the second of the stream, so a re-run finds them again.
        start, end = max(0.0, h.start_s - reserve), min(chat.duration, h.end_s + reserve)
        file = folder / f"excerpt_{h.spike_s:06d}.mp4"
        if not file.exists():
            say(f"Downloading excerpt {number} of {len(ranked)} ...")
            download_excerpt(vod, file, start, end)
        clip = folder / f"clip_{h.spike_s:06d}.mp4"
        say(f"Cutting and rendering clip {number} of {len(ranked)} ...")
        # From here on, times count from the start of the excerpt file.
        cut_start, cut_end, words = h.start_s - start, h.end_s - start, []
        if cfg["subtitles"]["enabled"] and transcribe.available():
            words = transcribe.transcribe(
                file, max(0.0, cut_start - _LISTEN_S), min(end - start, cut_end + _LISTEN_S),
                streamer["language"], cfg["subtitles"]["model"],
            )
            cut_start, cut_end = fine_cut(words, cut_start, cut_end, cfg["clip"], end - start)
        spoken = [
            Word(w.start - cut_start, w.end - cut_start, w.text)
            for w in words if w.start >= cut_start and w.end <= cut_end
        ]
        text = " ".join(w.text for w in spoken)
        suggestion = suggest(
            h.label, streamer["language"], text, streamer["display_name"], h.game, cfg["suggest"]
        )
        ass = clip.with_suffix(".ass")
        ass.write_text(
            build_ass(spoken, cfg["subtitles"], streamer["language"], hook=suggestion["hooks"][0],
                      hook_y=hook_position(layout_for(streamer), streamer, cfg["render"])),
            encoding="utf-8",
        )
        loud = loudest_moment(levels, start + cut_start, start + cut_end, offset,
                              cfg["render"]["zoom"]["min_rise_db"])
        zoom_at = None if loud is None else loud - (start + cut_start)
        render(file, clip, cut_start, cut_end, cfg, login, ass=ass, zoom_at=zoom_at)
        candidates.append(
            {"rank": number, **asdict(h), "file": file.name, "file_start_s": start, "file_end_s": end,
             "clip": clip.name, "clip_start_s": round(start + cut_start, 2), "clip_end_s": round(start + cut_end, 2),
             **suggestion, "text": text, "zoom_at_s": zoom_at}
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
