"""Highlight detection on synthetic chat logs in TwitchDownloader's JSON format."""
import json
import random

import pytest

from clipforge.config import build_config, detect_settings
from clipforge.detect import detect, read_chat

NOISE = ["hallo", "was geht", "lol", "wer ist noch da", "KEKW", "ja", "nein", "gg", "wann gta 6", "LUL", "ok", "moin"]
LAUGH = ["KEKW", "OMEGALUL", "LUL xD", "KEKW KEKW KEKW", "HAHAHA KEKW", "ICANT"]
HYPE = ["Pog", "POGGERS", "PogU PogU", "LETSGO", "EZ Clap"]
PROMPTED = ["1", "2", "1", "YT", "hallo", "ja", "nein", "mute"]  # polls and roll calls, not reactions
SPELLED_OUT = ["hahaha", "HAHAHAHA", "xD", "lol", "xDDD", "hahah was"]


def settings(games=(), emotes=None, **detect_overrides):
    streamer = {"language": "de", "games": list(games), "emotes": emotes or {}, "detect": detect_overrides}
    return detect_settings(build_config({"streamers": {"test": streamer}}), "test")


class ChatLog:
    """Builds a chat log file the way TwitchDownloaderCLI writes it."""

    def __init__(self, duration, seed=1):
        self.duration = duration
        self.rng = random.Random(seed)
        self.comments = []
        self.chapters = []

    def say(self, t, user, body, twitch_emote=False):
        self.comments.append(
            {
                "_id": f"{user}-{t}",
                "content_offset_seconds": t,
                "commenter": {"display_name": user, "_id": user, "name": user},
                "message": {
                    "body": body,
                    "fragments": [{"text": body, "emoticon": {"emoticon_id": "1"} if twitch_emote else None}],
                },
            }
        )

    def noise(self, rate, start=0.0):
        """Unrelated messages arriving at random, `rate` per second on average."""
        users = max(30, int(rate * 300))
        t = start + self.rng.expovariate(rate)
        while t < self.duration:
            self.say(t, f"viewer{self.rng.randrange(users)}", self.rng.choice(NOISE))
            t += self.rng.expovariate(rate)

    def burst(self, at, messages=80, users=60, texts=LAUGH, spread=8.0):
        """Many viewers reacting to something within a few seconds."""
        for _ in range(messages):
            self.say(at + self.rng.uniform(0, spread), f"fan{self.rng.randrange(users)}", self.rng.choice(texts))

    def chapter(self, start, end, game):
        self.chapters.append(
            {"startMilliseconds": start * 1000, "lengthMilliseconds": (end - start) * 1000, "gameDisplayName": game}
        )

    def write(self, tmp_path):
        path = tmp_path / "chat.json"
        log = {
            "streamer": {"name": "test", "id": 1},
            "video": {"title": "Test stream", "id": "1", "start": 0, "end": self.duration, "chapters": self.chapters},
            "comments": sorted(self.comments, key=lambda c: c["content_offset_seconds"]),
        }
        path.write_text(json.dumps(log), encoding="utf-8")
        return path


def near(highlight, at):
    """The detected onset lies within a few seconds of where the burst was placed."""
    return at - 5 <= highlight.spike_s <= at + 3


def test_finds_every_hype_moment(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    for at in (600, 1800, 3000):
        log.burst(at)

    highlights = detect(read_chat(log.write(tmp_path)), settings())

    found = sorted(highlights, key=lambda h: h.spike_s)
    assert len(found) == 3
    assert all(near(h, at) for h, at in zip(found, (600, 1800, 3000)))


def test_rough_clip_window_runs_from_20s_before_to_8s_after_the_spike(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    log.burst(1000)

    (highlight,) = detect(read_chat(log.write(tmp_path)), settings())

    assert highlight.start_s == highlight.spike_s - 20
    assert highlight.end_s == highlight.spike_s + 8


def test_single_spammer_creates_no_highlight(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    for i in range(60):
        log.say(900 + i * 0.08, "spammer", "KEKW KEKW KEKW")

    assert detect(read_chat(log.write(tmp_path)), settings()) == []


def test_a_handful_of_chatters_is_not_enough(tmp_path):
    log = ChatLog(3600)  # nobody else reacts at that moment
    for i in range(60):
        log.say(900 + i * 0.08, f"friend{i % 4}", "KEKW")

    assert detect(read_chat(log.write(tmp_path)), settings()) == []


@pytest.mark.parametrize("rate", [0.3, 1.0, 5.0])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_normal_chat_noise_creates_no_highlight(tmp_path, rate, seed):
    log = ChatLog(3600, seed=seed)
    log.noise(rate)

    assert detect(read_chat(log.write(tmp_path)), settings()) == []


def test_no_false_alarm_at_stream_start(tmp_path):
    log = ChatLog(1800)
    log.noise(2.0)  # chat is lively from the first second, before any history exists
    for i in range(15):
        log.say(i * 2.0, f"regular{i}", "moin")

    assert detect(read_chat(log.write(tmp_path)), settings()) == []


def test_hype_moment_in_the_first_minute_is_still_found(tmp_path):
    log = ChatLog(1800)
    log.noise(1.0)
    log.burst(40)

    (highlight,) = detect(read_chat(log.write(tmp_path)), settings())

    assert near(highlight, 40)


def test_bursts_closer_than_the_debounce_become_one_highlight(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    log.burst(1000)
    log.burst(1012)

    assert len(detect(read_chat(log.write(tmp_path)), settings())) == 1


def test_bursts_further_apart_than_the_debounce_stay_separate(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    log.burst(1000)
    log.burst(1060)

    assert len(detect(read_chat(log.write(tmp_path)), settings())) == 2


def test_label_follows_the_dominant_emote_group(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    log.burst(600, texts=LAUGH)
    log.burst(1800, texts=HYPE)

    found = sorted(detect(read_chat(log.write(tmp_path)), settings()), key=lambda h: h.spike_s)

    assert [h.label for h in found] == ["laugh", "hype"]


def test_polls_and_roll_calls_create_no_highlight(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    log.burst(600, messages=120, users=100, texts=PROMPTED)

    assert detect(read_chat(log.write(tmp_path)), settings()) == []


def test_laughter_spelled_out_counts_as_a_reaction(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    log.burst(600, texts=SPELLED_OUT)

    (highlight,) = detect(read_chat(log.write(tmp_path)), settings())

    assert highlight.label == "laugh"


def test_question_mark_spam_counts_as_shock(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    log.burst(600, texts=["???", "??", "?????", "was ???"])

    (highlight,) = detect(read_chat(log.write(tmp_path)), settings())

    assert highlight.label == "shock"


def test_emotes_outside_the_lists_do_not_count(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    log.burst(600, texts=["DinoDance", "someChannelHello", "catJAM"])  # dancing and greeting, not a reaction

    assert detect(read_chat(log.write(tmp_path)), settings()) == []


def test_twitch_emotes_outside_the_lists_do_not_count_either(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    for i in range(80):
        log.say(600 + i * 0.1, f"sub{i}", "someChannelHello", twitch_emote=True)

    assert detect(read_chat(log.write(tmp_path)), settings()) == []


def test_channel_emotes_from_the_config_count_and_carry_their_label(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    log.burst(600, texts=["someChannelLaugh"])

    (highlight,) = detect(read_chat(log.write(tmp_path)), settings(emotes={"laugh": ["someChannelLaugh"]}))

    assert highlight.label == "laugh"


def test_hype_words_count_as_reactions_without_a_label(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    log.burst(600, texts=["!clip", "DIGGA", "alter!!", "digga was"])

    (highlight,) = detect(read_chat(log.write(tmp_path)), settings())

    assert highlight.label is None


def test_a_bigger_reaction_scores_higher(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    log.burst(600, messages=60)
    log.burst(1800, messages=200, users=200)

    small, big = sorted(detect(read_chat(log.write(tmp_path)), settings()), key=lambda h: h.spike_s)

    assert big.score > small.score


def test_game_filter_keeps_only_listed_games(tmp_path):
    log = ChatLog(3600)
    log.chapter(0, 1500, "Just Chatting")
    log.chapter(1500, 3600, "Grand Theft Auto V")
    log.noise(1.0)
    log.burst(600)
    log.burst(1800)

    (highlight,) = detect(read_chat(log.write(tmp_path)), settings(games=["grand theft auto v"]))

    assert near(highlight, 1800)
    assert highlight.game == "Grand Theft Auto V"


def test_without_game_filter_every_chapter_counts(tmp_path):
    log = ChatLog(3600)
    log.chapter(0, 1500, "Just Chatting")
    log.chapter(1500, 3600, "Grand Theft Auto V")
    log.noise(1.0)
    log.burst(600)
    log.burst(1800)

    assert len(detect(read_chat(log.write(tmp_path)), settings())) == 2


def test_highlights_come_strongest_first(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    sizes = {600: 60, 1200: 200, 1800: 80, 2400: 160, 3000: 120}
    for at, size in sizes.items():
        log.burst(at, messages=size, users=size)

    highlights = detect(read_chat(log.write(tmp_path)), settings())

    assert [round(h.spike_s, -2) for h in highlights] == [1200, 2400, 3000, 1800, 600]


def test_min_score_drops_weaker_highlights(tmp_path):
    log = ChatLog(3600)
    log.noise(1.0)
    log.burst(600, messages=60)
    log.burst(1800, messages=200, users=200)
    chat = read_chat(log.write(tmp_path))
    weak, strong = sorted(detect(chat, settings()), key=lambda h: h.score)

    highlights = detect(chat, settings(min_score=(weak.score + strong.score) / 2))

    assert highlights == [strong]


def test_reader_skips_subscription_notices(tmp_path):
    log = ChatLog(60)
    log.say(1.0, "anna", "hallo")
    log.say(2.0, "ben", "ben subscribed at Tier 1. They've subscribed for 3 months! KEKW")
    log.say(2.5, "dora", "dora gifted a Tier 1 sub to emil!")
    log.say(3.0, "cem", "KEKW")

    chat = read_chat(log.write(tmp_path))

    assert [m.user for m in chat.messages] == ["anna", "cem"]


def test_reader_reads_streamer_duration_and_chapters(tmp_path):
    log = ChatLog(3600)
    log.chapter(0, 1500, "Just Chatting")
    log.chapter(1500, 3600, "Grand Theft Auto V")

    chat = read_chat(log.write(tmp_path))

    assert chat.streamer == "test"
    assert chat.duration == 3600
    assert [(c.start, c.end, c.game) for c in chat.chapters] == [
        (0, 1500, "Just Chatting"),
        (1500, 3600, "Grand Theft Auto V"),
    ]
