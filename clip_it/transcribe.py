"""Speech to text with word timestamps. Optional: needs the "subtitles" extra (faster-whisper)."""
from __future__ import annotations

import functools
import subprocess
from pathlib import Path

from .subtitles import Word
from .twitch import ToolError, find_tool

MODELS = Path("data/models")  # a model folder placed here is used instead of downloading


def available() -> bool:
    """Whether faster-whisper is installed; without it clips are made without subtitles."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


@functools.cache
def _model(name: str):
    from faster_whisper import WhisperModel

    # data/models/<name> if it exists; otherwise faster-whisper downloads the model into
    # the Hugging Face cache in the user's home folder on first use.
    local = MODELS / name
    return WhisperModel(str(local) if local.is_dir() else name, device="auto", compute_type="int8")


def transcribe(media: Path, start: float, end: float, language: str, model: str) -> list[Word]:
    """The words spoken between `start` and `end` seconds of a media file, timed from the file's start."""
    import numpy

    # ffmpeg decodes just this window to 16 kHz mono. faster-whisper's own decoder (PyAV)
    # would read the whole file, and its 1.2.1 release does not work with PyAV 19.
    ffmpeg = find_tool("ffmpeg")
    if not ffmpeg:
        raise ToolError("ffmpeg not found")
    decoded = subprocess.run(
        [ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(media),
         "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True,
    )
    if decoded.returncode != 0:
        raise ToolError(f"ffmpeg could not read the audio of {media}")
    samples = numpy.frombuffer(decoded.stdout, numpy.float32)
    segments, _ = _model(model).transcribe(
        samples, language=language, word_timestamps=True, condition_on_previous_text=False
    )
    return [
        Word(start + word.start, start + word.end, word.word.strip())
        for segment in segments
        for word in segment.words or []
        if word.word.strip()
    ]
