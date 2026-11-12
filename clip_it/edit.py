"""Fine cut: where a clip starts and ends."""
from __future__ import annotations

from .subtitles import Word

_PAUSE_S = 0.7  # a silence this long ends a sentence
_MAX_BACK_S = 8.0  # how far the start may move back to reach the beginning of a sentence
_LEAD_GAP_S = 2.0  # a silence this long after the first words of a clip is cut away ...
_MAX_SKIP_S = 10.0  # ... if it ends within this many seconds of the clip's start
_PAD_S = 0.15  # air before the first word
_TAIL_S = 0.4  # ... and after the last one, so the reaction can ring out


def _sentences(words: list[Word]) -> list[list[Word]]:
    sentences: list[list[Word]] = []
    for word in words:
        previous = sentences[-1][-1] if sentences else None
        if previous is None or previous.text.rstrip()[-1:] in ".?!" or word.start - previous.end > _PAUSE_S:
            sentences.append([])
        sentences[-1].append(word)
    return sentences


def fine_cut(
    words: list[Word], rough_start: float, rough_end: float, limits: dict, total: float
) -> tuple[float, float]:
    """Move the rough window onto sentence boundaries. All times are seconds of the excerpt.

    `limits` holds min_s, target_max_s and hard_max_s; `total` is the excerpt's length.
    Without words (no speech, or no transcript) the rough window is returned.
    """
    if not words:
        return rough_start, rough_end
    sentences = _sentences(words)

    # Start: the beginning of the sentence running at the rough start. If that began long
    # ago, the nearest word boundary, so that at least no word is cut.
    sentence_starts = [s[0].start for s in sentences if rough_start - _MAX_BACK_S <= s[0].start <= rough_start]
    word_starts = [w.start for w in words if w.start <= rough_start]
    start = sentence_starts[-1] if sentence_starts else word_starts[-1] if word_starts else rough_start
    # A word or two followed by a long silence makes a weak opening: start after the silence,
    # as long as that is early in the clip, well before the moment the chat reacts to.
    following = [w for w in words if w.start >= start]
    opening = start
    for previous, word in zip(following, following[1:]):
        if word.start > opening + _MAX_SKIP_S:
            break
        if word.start - previous.end > _LEAD_GAP_S:
            start = word.start

    # End: the end of the sentence running at the rough end ...
    ends = [s[-1].end for s in sentences]
    end = next((e for e in ends if e >= rough_end), rough_end)
    # ... or of a later one if the clip would be too short ...
    while end - start < limits["min_s"]:
        later = next((e for e in ends if e > end), None)
        end = later if later is not None else start + limits["min_s"]
    # ... or of an earlier one if it would run past the target length ...
    if end - start > limits["target_max_s"]:
        earlier = [e for e in ends if rough_end - 3 <= e <= start + limits["target_max_s"]]
        end = earlier[-1] if earlier else end
    # ... and never beyond the hard limit: then it stops after the last word that still fits.
    if end + _TAIL_S - (start - _PAD_S) > limits["hard_max_s"]:
        latest = start - _PAD_S + limits["hard_max_s"] - _TAIL_S
        end = max((w.end for w in words if w.end <= latest), default=latest)
    return max(0.0, start - _PAD_S), min(total, end + _TAIL_S)
