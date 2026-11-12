"""Subtitles in ASS format: a few words at a time, the spoken word highlighted."""
from __future__ import annotations

from dataclasses import dataclass

FONT_NAME = "Montserrat Black"
WIDTH, HEIGHT = 1080, 1920
_PAUSE_S = 0.6  # a longer silence between two words starts a new cue
_KEPT = "?!"  # punctuation that stays in the picture


@dataclass(frozen=True)
class Word:
    start: float  # seconds from the start of the clip
    end: float
    text: str


def cues(words: list[Word], max_words: int) -> list[list[Word]]:
    """Group words into cues: at most `max_words`, broken at pauses and sentence ends."""
    groups: list[list[Word]] = []
    for word in words:
        previous = groups[-1][-1] if groups else None
        if (
            previous is None
            or len(groups[-1]) >= max_words
            or word.start - previous.end > _PAUSE_S
            or previous.text.rstrip()[-1:] in ".?!"
        ):
            groups.append([])
        groups[-1].append(word)
    return groups


def censor(word: str, banned: set[str]) -> str:
    """Replace a banned word by its first letter and asterisks; punctuation stays."""
    core = word.rstrip(".,!?")
    if core.lower() not in banned:
        return word
    return core[0] + "*" * (len(core) - 1) + word[len(core):]


def _colour(hex_colour: str) -> str:
    """#RRGGBB as ASS writes it: &HBBGGRR&."""
    r, g, b = hex_colour[1:3], hex_colour[3:5], hex_colour[5:7]
    return f"&H{b}{g}{r}&".upper()


def _clock(seconds: float) -> str:
    centis = max(0, round(seconds * 100))
    return f"{centis // 360000}:{centis // 6000 % 60:02d}:{centis // 100 % 60:02d}.{centis % 100:02d}"


def _shown(text: str, s: dict, banned: set[str]) -> str:
    text = censor(text.strip(), banned)
    text = "".join(ch for ch in text if ch.isalnum() or ch in _KEPT + "*'-")
    return text.upper() if s["uppercase"] else text


def build_ass(
    words: list[Word], s: dict, language: str = "", hook: str | None = None, hook_y: int = HEIGHT // 2
) -> str:
    """The subtitle file for one clip. `s` is the "subtitles" section of the config."""
    banned = {w.lower() for w in s["censor"].get(language) or []}
    white, outline, highlight = _colour(s["color"]), _colour(s["outline"]), _colour(s["highlight"])
    style = "0,0,0,0,100,100,0,0,{border},{width},0,5,60,60,0,1"
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {WIDTH}",
        f"PlayResY: {HEIGHT}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Sub,{FONT_NAME},{s['size']},{white[:-1]},{white[:-1]},{outline[:-1]},{outline[:-1]},"
        + style.format(border=1, width=s["outline_px"]),
        # The hook sits in an opaque box in the highlight colour.
        f"Style: Hook,{FONT_NAME},{s['hook_size']},{outline[:-1]},{outline[:-1]},{highlight[:-1]},{highlight[:-1]},"
        + style.format(border=3, width=14),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if hook:
        text = " ".join(_shown(part, {**s, "uppercase": True}, set()) for part in hook.split())
        lines.append(
            f"Dialogue: 1,{_clock(0)},{_clock(s['hook_duration_s'])},Hook,,0,0,0,,{{\\pos({WIDTH // 2},{hook_y})}}{text}"
        )
    position = f"{{\\pos({WIDTH // 2},{round(HEIGHT * s['y_position'])})}}"
    pop = f"\\fscx{s['pop_scale']}\\fscy{s['pop_scale']}\\t(0,150,\\fscx100\\fscy100)"
    for group in cues(words, s["words_per_cue"]):
        shown = [_shown(w.text, s, banned) for w in group]
        for i, word in enumerate(group):
            end = group[i + 1].start if i + 1 < len(group) else word.end
            parts = [f"{{\\c{highlight}{pop}}}{t}{{\\r}}" if j == i else t for j, t in enumerate(shown)]
            lines.append(f"Dialogue: 0,{_clock(word.start)},{_clock(end)},Sub,,0,0,0,,{position}{' '.join(parts)}")
    return "\n".join(lines) + "\n"
