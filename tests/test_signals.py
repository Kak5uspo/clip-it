"""Loudness of the audio track and its effect on the ranking."""
import shutil
import subprocess

import pytest

from clip_it.detect import Highlight
from clip_it.signals import loudest_moment, loudness, rank

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")

SETTINGS = {"audio_weight": 0.5, "skip_muted": True, "top_n": 8}


def highlight(spike_s, score):
    return Highlight(
        spike_s=spike_s, start_s=spike_s - 20, end_s=spike_s + 8,
        score=score, rate=2.0, baseline=0.1, chatters=8, label="laugh", game=None,
    )


def stream_levels(seconds=600):
    """A stream at about -30 dB with a little natural variation."""
    return [-30.0 + (i % 5) for i in range(seconds)]


@needs_ffmpeg
def test_loudness_gives_one_value_per_second_and_loud_seconds_stand_out(tmp_path):
    audio = tmp_path / "tone.m4a"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
         "-af", "volume='if(between(t,10,13),1.0,0.02)':eval=frame", str(audio)],
        check=True,
    )

    levels = loudness(audio)

    assert 29 <= len(levels) <= 31
    assert min(levels[10:13]) > max(levels[:9] + levels[14:29]) + 20  # decibels


def test_a_loud_moment_outranks_an_equally_strong_quiet_one():
    levels = stream_levels()
    levels[300:304] = [-8.0] * 4  # someone screams
    quiet, loud = highlight(120, 4.0), highlight(310, 4.0)

    ranked, _ = rank([quiet, loud], levels, SETTINGS)

    assert [h.spike_s for h in ranked] == [310, 120]
    assert ranked[0].score > 4.0
    assert ranked[1].score == 4.0


def test_loudness_is_only_a_bonus_and_cannot_beat_a_much_stronger_chat_reaction():
    levels = stream_levels()
    levels[300:304] = [-8.0] * 4
    strong_quiet, weak_loud = highlight(120, 9.0), highlight(310, 3.5)

    ranked, _ = rank([weak_loud, strong_quiet], levels, SETTINGS)

    assert [h.spike_s for h in ranked] == [120, 310]


def test_a_highlight_in_a_muted_passage_is_dropped_and_reported():
    levels = stream_levels()
    levels[280:330] = [float("-inf")] * 50  # Twitch replaced the audio with silence
    audible, muted = highlight(120, 4.0), highlight(310, 6.0)

    ranked, dropped = rank([audible, muted], levels, SETTINGS)

    assert [h.spike_s for h in ranked] == [120]
    assert [h.spike_s for h in dropped] == [310]


def test_muted_highlights_stay_when_skipping_is_turned_off():
    levels = stream_levels()
    levels[280:330] = [float("-inf")] * 50

    ranked, dropped = rank([highlight(310, 6.0)], levels, {**SETTINGS, "skip_muted": False})

    assert len(ranked) == 1
    assert dropped == []


def test_levels_can_start_later_than_the_stream():
    levels = stream_levels(200)  # audio was downloaded from second 1000 on
    levels[100:104] = [-8.0] * 4
    quiet, loud = highlight(1040, 4.0), highlight(1110, 4.0)

    ranked, _ = rank([quiet, loud], levels, SETTINGS, offset=1000)

    assert [h.spike_s for h in ranked] == [1110, 1040]


def test_without_audio_the_chat_score_decides():
    ranked, dropped = rank([highlight(100, 3.5), highlight(500, 4.5)], None, SETTINGS)

    assert [h.spike_s for h in ranked] == [500, 100]
    assert dropped == []


def test_only_the_top_n_are_kept():
    highlights = [highlight(100 * i, float(i)) for i in range(1, 6)]

    ranked, _ = rank(highlights, None, {**SETTINGS, "top_n": 2})

    assert [h.score for h in ranked] == [5.0, 4.0]


def test_the_loudest_moment_of_a_clip_is_found_in_stream_seconds():
    levels = stream_levels()
    levels[320:322] = [-6.0, -6.0]  # a scream 20 s into the clip

    assert loudest_moment(levels, 300, 330, offset=0, min_rise_db=6) == 320


def test_no_loudest_moment_when_nothing_stands_out():
    assert loudest_moment(stream_levels(), 300, 330, offset=0, min_rise_db=6) is None


def test_the_first_second_of_a_clip_is_not_used_for_the_zoom():
    levels = stream_levels()
    levels[300] = -6.0  # the hook is on screen then

    assert loudest_moment(levels, 300, 330, offset=0, min_rise_db=6) is None


def test_without_audio_there_is_no_loudest_moment():
    assert loudest_moment(None, 300, 330, offset=0, min_rise_db=6) is None
