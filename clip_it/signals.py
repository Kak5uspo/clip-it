"""Signals beside the chat: loudness of the audio track, muted passages, final ranking."""
from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from statistics import fmean, median

from .detect import Highlight
from .twitch import ToolError, find_tool

_KEY = "lavfi.astats.Overall.RMS_level="
_SILENT_DB = -90.0  # at or below this a second is digital silence: Twitch muted it
_MUTED_SECONDS = 3  # this many silent seconds make a clip window unusable
_BONUS_FROM = 2.0  # loudness only counts from this many spreads above the stream's normal level
_BONUS_CAP = 5.0  # ... and lifts a score by at most audio_weight x this


def loudness(audio: Path) -> list[float]:
    """RMS level in dB for every second of an audio file (-inf for digital silence)."""
    ffmpeg = find_tool("ffmpeg")
    if not ffmpeg:
        raise ToolError("ffmpeg not found")
    result = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(audio), "-map", "0:a:0", "-af",
         "aresample=8000,asetnsamples=n=8000:p=0,astats=metadata=1:reset=1,"
         "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise ToolError(f"ffmpeg could not read {audio}: {result.stderr.strip()[-300:]}")
    return [float(line[len(_KEY):]) for line in result.stdout.splitlines() if line.startswith(_KEY)]


def loudest_moment(
    levels: list[float] | None, start: float, end: float, offset: int = 0, min_rise_db: float = 6.0
) -> int | None:
    """Stream second of the loudest moment between `start` and `end`, or None if nothing stands out.

    The first second is skipped (the hook is on screen then). A moment counts only if it is
    at least `min_rise_db` louder than the clip's typical level.
    """
    if not levels:
        return None
    seconds = [s for s in range(int(start) + 1, int(end)) if 0 <= s - offset < len(levels)]
    audible = [(levels[s - offset], s) for s in seconds if levels[s - offset] > _SILENT_DB]
    if len(audible) < 3:
        return None
    loudest, second = max(audible, key=lambda pair: pair[0])  # ties: the earliest second
    return second if loudest - median(v for v, _ in audible) >= min_rise_db else None


def rank(
    highlights: list[Highlight], levels: list[float] | None, s: dict, offset: int = 0
) -> tuple[list[Highlight], list[Highlight]]:
    """Order highlights by chat score plus a bonus for loud moments.

    `levels` is the loudness per second, starting at second `offset` of the
    stream; None ranks by chat alone. Returns the top highlights and those
    dropped because their audio is muted.
    """
    audible = [v for v in levels or [] if v > _SILENT_DB]
    normal = median(audible) if audible else 0.0
    spread = max(1.4826 * median(abs(v - normal) for v in audible), 1.0) if audible else 1.0

    kept, dropped = [], []
    for h in highlights:
        window = (levels or [])[max(0, int(h.start_s) - offset) : max(0, int(h.end_s) - offset + 1)]
        if s["skip_muted"] and sum(v <= _SILENT_DB for v in window) >= _MUTED_SECONDS:
            dropped.append(h)
            continue
        loudest = sorted(v for v in window if v > _SILENT_DB)[-3:]
        bonus = 0.0
        if loudest:
            bonus = min(max((fmean(loudest) - normal) / spread - _BONUS_FROM, 0.0), _BONUS_CAP)
        kept.append(replace(h, score=round(h.score + s["audio_weight"] * bonus, 2)))
    kept.sort(key=lambda h: h.score, reverse=True)
    return kept[: s["top_n"]], dropped
