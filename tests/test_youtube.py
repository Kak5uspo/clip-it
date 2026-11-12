"""YouTube publishing: slots, titles, the permission lock and the upload request."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from clip_it import youtube
from clip_it.config import build_config

BERLIN = ZoneInfo("Europe/Berlin")


def config(**streamer):
    return build_config({"streamers": {"test": {"display_name": "Tester", **streamer}}})


def at(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=BERLIN)


SLOTS = ["12:00", "15:00", "18:00", "21:00"]


def test_next_slot_is_the_next_slot_time_today():
    assert youtube.next_slot(at(19, 13, 30), SLOTS, "Europe/Berlin", taken=[]) == at(19, 15)


def test_a_slot_that_starts_too_soon_is_skipped():
    # 14:50: the 15:00 slot is less than a quarter of an hour away
    assert youtube.next_slot(at(19, 14, 50), SLOTS, "Europe/Berlin", taken=[]) == at(19, 18)


def test_taken_slots_are_skipped_and_the_day_rolls_over():
    taken = [at(19, 21).astimezone(timezone.utc)]

    assert youtube.next_slot(at(19, 19), SLOTS, "Europe/Berlin", taken=taken) == at(20, 12)


def test_title_follows_the_template():
    cfg = config()
    record = {"title": "Er drückt aus Versehen F", "hashtags": ["#gta5"], "game": "Grand Theft Auto V"}

    title = youtube.video_title(record, cfg["streamers"]["test"], "{title} | {streamer} #shorts")

    assert title == "Er drückt aus Versehen F | Tester #shorts"


def test_the_streamer_is_not_named_twice():
    cfg = config()
    record = {"title": "Tester fährt wie noch nie", "hashtags": [], "game": None}

    title = youtube.video_title(record, cfg["streamers"]["test"], "{title} | {streamer} GTA 6 #shorts")

    assert title == "Tester fährt wie noch nie | GTA 6 #shorts"


def test_a_long_title_is_shortened_to_fit_100_characters_and_keeps_the_template():
    cfg = config()
    record = {"title": "Sehr " * 40 + "lang", "hashtags": [], "game": None}

    title = youtube.video_title(record, cfg["streamers"]["test"], "{title} | {streamer} #shorts")

    assert len(title) <= 100 and title.endswith("… | Tester #shorts")


def test_angle_brackets_are_removed_because_youtube_rejects_them():
    cfg = config()
    record = {"title": "Was <das> ist", "hashtags": [], "game": None}

    assert "<" not in youtube.video_title(record, cfg["streamers"]["test"], "{title}")


def test_upload_is_refused_without_permission(tmp_path):
    cfg = config()

    with pytest.raises(youtube.UploadRefused, match="permission"):
        youtube.check_permission(cfg["streamers"]["test"], "test", tmp_path)


def test_upload_is_refused_when_the_proof_file_is_missing(tmp_path):
    cfg = config(permission={"date": "2026-11-12", "via": "Discord", "proof": "test.png"})

    with pytest.raises(youtube.UploadRefused, match="test.png"):
        youtube.check_permission(cfg["streamers"]["test"], "test", tmp_path)


def test_upload_is_allowed_with_proof_or_for_your_own_channel(tmp_path):
    (tmp_path / "test.png").write_bytes(b"png")
    with_proof = config(permission={"date": "2026-11-12", "via": "Discord", "proof": "test.png"})
    own = config(own_channel=True)

    youtube.check_permission(with_proof["streamers"]["test"], "test", tmp_path)
    youtube.check_permission(own["streamers"]["test"], "test", tmp_path)


class FakeYouTube:
    """Stands in for the API client: records the request and answers like YouTube."""

    def __init__(self):
        self.request = None

    def videos(self):
        return self

    def insert(self, part, body, media_body):
        self.request = {"part": part, "body": body, "media": media_body}
        return self

    def next_chunk(self):
        return None, {"id": "abc123"}


def test_a_scheduled_upload_is_private_with_a_publish_time(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"0" * 100)
    fake = FakeYouTube()
    when = at(19, 18)

    video_id = youtube.upload(fake, video, "Titel", "Beschreibung", ["gta5"], "de", publish_at=when)

    assert video_id == "abc123"
    status = fake.request["body"]["status"]
    assert status["privacyStatus"] == "private"
    assert status["publishAt"] == "2026-11-19T17:00:00Z"
    assert status["selfDeclaredMadeForKids"] is False
    snippet = fake.request["body"]["snippet"]
    assert snippet["categoryId"] == "20" and snippet["tags"] == ["gta5"] and snippet["defaultLanguage"] == "de"


def test_an_upload_without_a_time_goes_public_at_once(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"0" * 100)
    fake = FakeYouTube()

    youtube.upload(fake, video, "Titel", "Beschreibung", [], "de", publish_at=None)

    status = fake.request["body"]["status"]
    assert status["privacyStatus"] == "public" and "publishAt" not in status


# --- publishing a clip record

from clip_it import clips  # noqa: E402
from test_clips import candidate, vod_folder  # noqa: E402


@pytest.fixture
def ready(tmp_path, monkeypatch):
    """A clip folder, a streamer with permission and a fake YouTube instead of the real one."""
    (tmp_path / "proof.png").write_bytes(b"png")
    cfg = build_config({"streamers": {"test": {"language": "de", "permission": {
        "date": "2026-11-12", "via": "Discord", "proof": "proof.png"}}}})
    folder = vod_folder(tmp_path, candidate(), candidate(spike_s=2000, clip="clip_002000.mp4"))
    for name in ("clip_001000.mp4", "clip_002000.mp4"):
        (folder / name).write_bytes(b"0" * 100)
    fake = FakeYouTube()
    monkeypatch.setattr(youtube, "service", lambda: fake)
    monkeypatch.setattr(youtube, "PERMISSIONS", tmp_path)
    return folder, cfg, fake


def test_publishing_uploads_into_the_next_slot_and_records_it(ready):
    folder, cfg, fake = ready

    record = clips.publish(folder, 1000, "slot", cfg, now=at(19, 13))

    assert record["youtube_id"] == "abc123" and record["status"] == "approved"
    assert record["publish_at"] == "2026-11-19T14:00:00+00:00"  # 15:00 in Berlin
    assert fake.request["body"]["snippet"]["title"] == "Titel | test #shorts"


def test_the_next_clip_takes_the_following_slot(ready):
    folder, cfg, _ = ready
    clips.publish(folder, 1000, "slot", cfg, now=at(19, 13))

    second = clips.publish(folder, 2000, "slot", cfg, now=at(19, 13))

    assert second["publish_at"] == "2026-11-19T17:00:00+00:00"  # 18:00 in Berlin


def test_a_clip_is_uploaded_only_once(ready):
    folder, cfg, _ = ready
    clips.publish(folder, 1000, "now", cfg)

    with pytest.raises(youtube.UploadRefused, match="already"):
        clips.publish(folder, 1000, "now", cfg)


def test_a_custom_time_in_the_past_is_refused(ready):
    folder, cfg, _ = ready

    with pytest.raises(youtube.UploadRefused, match="past"):
        clips.publish(folder, 1000, "2026-11-01T12:00", cfg, now=at(19, 13))


def test_without_permission_nothing_is_uploaded_and_nothing_changes(ready, monkeypatch, tmp_path):
    folder, cfg, fake = ready
    monkeypatch.setattr(youtube, "PERMISSIONS", tmp_path / "elsewhere")
    before = (folder / "candidates.json").read_text(encoding="utf-8")

    with pytest.raises(youtube.UploadRefused, match="proof"):
        clips.publish(folder, 1000, "slot", cfg)

    assert fake.request is None
    assert (folder / "candidates.json").read_text(encoding="utf-8") == before
