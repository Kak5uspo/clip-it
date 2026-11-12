"""Publishing to YouTube: sign-in, upload, scheduling into posting slots."""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SECRET = Path("data/google_client_secret.json")  # the OAuth client downloaded from Google Cloud
TOKEN = Path("data/google_token.json")  # your sign-in; never commit it
PERMISSIONS = Path("data/permissions")
# Upload, and read-only access for the view counts in the statistics later.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
_LEAD = timedelta(minutes=15)  # a slot closer than this is skipped, so the upload has time to finish
_TITLE_MAX = 100  # YouTube's limit


class UploadRefused(Exception):
    """Uploading is not possible right now; the message says why and what to do."""


def check_permission(streamer: dict, login: str, folder: Path = PERMISSIONS) -> None:
    """Refuse uploads of a streamer who has not agreed in writing (unless it is your own channel)."""
    if streamer["own_channel"]:
        return
    permission = streamer["permission"]
    if not (permission["date"] and permission["via"] and permission["proof"]):
        raise UploadRefused(
            f"No written permission from {login} is recorded. Add streamers.{login}.permission "
            "(date, via, proof) to config.yaml, with a screenshot of the agreement in data/permissions/."
        )
    if not (folder / permission["proof"]).exists():
        raise UploadRefused(f"The permission proof {permission['proof']} is missing in {folder}.")


def next_slot(now: datetime, slots: list[str], tz: str, taken: list[datetime]) -> datetime:
    """The first slot at least a quarter of an hour from now that no other clip uses."""
    zone = ZoneInfo(tz)
    local_now = now.astimezone(zone)
    taken_utc = {t.astimezone(timezone.utc) for t in taken}
    times = sorted(time.fromisoformat(s) for s in slots)
    for day in range(366):
        date = (local_now + timedelta(days=day)).date()
        for t in times:
            candidate = datetime.combine(date, t, tzinfo=zone)
            if candidate >= local_now + _LEAD and candidate.astimezone(timezone.utc) not in taken_utc:
                return candidate
    raise UploadRefused("no free posting slot within a year")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("<", "").replace(">", "")).strip()


def video_title(record: dict, streamer: dict, template: str) -> str:
    """The YouTube title from the template; the streamer's name only once, at most 100 characters."""
    name = streamer["display_name"]
    clip_title = _clean(record["title"])
    fields = {"streamer": "" if name.lower() in clip_title.lower() else name, "game": record.get("game") or ""}
    rest = _clean(template.replace("{title}", "\0").format(**fields))
    rest = _clean(re.sub(r"\|\s*(?=#|$)", "", rest))  # a separator left in front of nothing
    room = _TITLE_MAX - len(rest.replace("\0", ""))
    if len(clip_title) > room:
        clip_title = clip_title[: max(0, room - 1)].rstrip() + "…"
    return rest.replace("\0", clip_title)


def description(record: dict, login: str, template: str) -> str:
    return template.format(title=_clean(record["title"]), login=login, hashtags=" ".join(record["hashtags"]))[:5000]


def upload(service, video: Path, title: str, text: str, tags: list[str], language: str,
           publish_at: datetime | None) -> str:
    """Upload a video and return its YouTube id.

    With `publish_at` the video is uploaded as private and YouTube publishes it at
    that time on its own; without it the video is public at once.
    """
    from googleapiclient.http import MediaFileUpload

    status = {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    if publish_at is not None:
        status["privacyStatus"] = "private"  # YouTube only schedules private videos
        status["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "snippet": {"title": title, "description": text, "tags": tags, "categoryId": "20",  # Gaming
                    "defaultLanguage": language, "defaultAudioLanguage": language},
        "status": status,
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", resumable=True, chunksize=-1)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()
    return response["id"]


def login() -> None:
    """Sign in to Google in the browser once and store the token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not SECRET.exists():
        raise UploadRefused(
            f"{SECRET} not found. Create an OAuth client of type 'Desktop app' in Google Cloud "
            "and save its JSON file there (see the README)."
        )
    credentials = InstalledAppFlow.from_client_secrets_file(str(SECRET), SCOPES).run_local_server(port=0)
    TOKEN.write_text(credentials.to_json(), encoding="utf-8")


def service():
    """An API client signed in with the stored token, refreshed when needed."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not TOKEN.exists():
        raise UploadRefused("Not signed in to YouTube. Run: uv run python -m clip_it youtube-login")
    credentials = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not credentials.valid:
        try:
            credentials.refresh(Request())
        except RefreshError:
            raise UploadRefused(
                "The YouTube sign-in has expired. Run: uv run python -m clip_it youtube-login"
            ) from None
        TOKEN.write_text(credentials.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)
