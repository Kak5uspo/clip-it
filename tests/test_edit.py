"""Fine cut: a clip starts and ends on sentence boundaries."""
import pytest

from clip_it.edit import fine_cut
from clip_it.subtitles import Word

LIMITS = {"min_s": 15, "target_max_s": 45, "hard_max_s": 59}
TOTAL = 148.0  # length of the downloaded excerpt


def sentence(start, end):
    """One sentence spoken without a pause from `start` to `end`, in words of half a second."""
    count = round((end - start) / 0.5)
    words = [Word(start + i * 0.5, start + (i + 1) * 0.5, "wort") for i in range(count)]
    return words[:-1] + [Word(words[-1].start, words[-1].end, "ende.")]


def test_the_clip_starts_with_the_sentence_that_is_running_at_the_rough_start():
    words = sentence(50, 54) + sentence(57, 63) + sentence(70, 75) + sentence(84, 90) + sentence(93, 96)

    start, _ = fine_cut(words, 60.0, 88.0, LIMITS, TOTAL)

    assert start == pytest.approx(57.0, abs=0.3)  # not 60, which is in the middle of the second sentence
    assert start <= 57.0  # a little air before the first word


def test_the_clip_ends_when_the_sentence_running_at_the_rough_end_is_finished():
    words = sentence(50, 54) + sentence(57, 63) + sentence(70, 75) + sentence(84, 90) + sentence(93, 96)

    _, end = fine_cut(words, 60.0, 88.0, LIMITS, TOTAL)

    assert end == pytest.approx(90.0, abs=0.6)  # not 88, which is in the middle of the fourth sentence
    assert end >= 90.0  # a short tail after the last word


def test_without_a_transcript_the_rough_window_stays():
    assert fine_cut([], 60.0, 88.0, LIMITS, TOTAL) == (60.0, 88.0)


def test_the_start_does_not_move_back_to_a_sentence_that_began_long_ago():
    words = sentence(30, 75) + sentence(84, 90)  # someone has been talking for half a minute

    start, _ = fine_cut(words, 60.0, 88.0, LIMITS, TOTAL)

    assert 59.0 <= start <= 60.0  # the nearest word boundary instead


def test_a_clip_that_would_be_too_short_runs_on_to_a_later_sentence_end():
    words = sentence(58, 64) + sentence(66, 72) + sentence(74, 80)

    start, end = fine_cut(words, 60.0, 65.0, LIMITS, TOTAL)

    assert end - start >= 15
    assert end == pytest.approx(80.0, abs=0.6)


def test_a_clip_never_exceeds_the_hard_limit_and_still_ends_between_words():
    words = sentence(58, 140)  # one endless sentence

    start, end = fine_cut(words, 60.0, 88.0, LIMITS, TOTAL)

    assert end - start <= 59
    assert (end - 0.4) % 0.5 == pytest.approx(0, abs=0.01) or (end - 0.4) % 0.5 == pytest.approx(0.5, abs=0.01)


def test_the_clip_stays_inside_the_excerpt():
    words = sentence(0.0, 6) + sentence(140, 147.9)

    start, end = fine_cut(words, 0.1, 146.0, {**LIMITS, "hard_max_s": 200, "target_max_s": 200}, TOTAL)

    assert start >= 0.0
    assert end <= TOTAL
