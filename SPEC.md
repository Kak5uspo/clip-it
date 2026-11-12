# ClipIt – Specification

Status: approved on 2026-11-11. Milestones 1 to 3 are implemented, 4 to 7 are open.

## 1. Goal

ClipIt is an open-source tool that finds highlights in the Twitch VODs of any streamer you configure, cuts and edits them into finished vertical clips on its own, and presents them in a local dashboard for review. Approved clips are uploaded to YouTube Shorts; for TikTok it provides the file and caption for manual posting.

The project will be published on GitHub as free to use. Nothing in the repository is tied to a specific streamer, game or channel: all of that lives in the user's local `config.yaml`.

## 2. Decisions

| Topic | Decision |
|---|---|
| License | MIT |
| Language | Everything in the repository is English: code, comments, CLI output, logs, dashboard, config keys, README, this spec |
| Content language | Subtitles, hooks and titles follow each streamer's `language` setting |
| Streamers | Any number, each one an entry in `config.yaml` |
| Source | Twitch only, VOD mode only in v1 |
| Download | Chat log and audio track of the whole stream first, then only the excerpts of the candidates |
| Muted passages | Candidates inside muted VOD segments are skipped |
| Signals | Chat activity (trigger) + emote categories + loudness + viewer clips (bonus) |
| Strictness | Only candidates above the threshold are rendered, no padding with weak ones |
| Clip length | Variable 15–45 s, hard limit 59 s |
| Layouts | `split` (facecam top, gameplay bottom) and `blur`; switchable per clip |
| Facecam | Fixed relative coordinates per streamer. Without coordinates the streamer falls back to `blur` |
| Subtitles | Montserrat Black, upper case, white with black outline, current word coloured with a slight pop, no emojis |
| Profanity | Censored in the subtitle text (`S***`), audio untouched |
| Hook, title, hashtags | AI suggestion (Claude API); rule-based fallback without a key |
| Effects | Auto-zoom and jump cuts; no sound effects, no music, no intro/outro |
| Credit | `twitch.tv/{login}` small and permanent in the picture |
| Output | 1080×1920, 60 fps, H.264 + AAC, loudness normalised |
| Dashboard | Preview, hook/title/hashtags, subtitle correction, layout/effects per clip, re-trimming on the raw excerpt, scheduling, statistics |
| Access | Localhost by default; optional LAN access with password |
| Approval | One click on "Approve" uploads to YouTube immediately |
| Posting | Next free slot (fixed times of day), overridable per clip |
| Trigger | Automatic on start and every 30 minutes, plus a button and a VOD link field |
| Clean-up | Audio track immediately, raw excerpts 14 days, rejected clips 7 days, uploaded clips 30 days; size limit configurable |
| Notifications | None (dashboard and log only) |
| Permission | Proof per streamer, or `own_channel: true`. Without either, the YouTube upload stays locked |
| Credentials | Every user brings their own Twitch app, Google Cloud project and Anthropic key. Nothing is shared in the repository |

## 3. Scope

**Version 1**
- Complete VOD mode: discover, download, detect, cut, subtitle, render
- Dashboard with approval
- YouTube upload with scheduling
- TikTok: download and caption to copy; the upload is manual (no unofficial APIs)

**First to slip past the release if time runs out:** jump cuts.

**Later**
- Live mode (streamlink, ring buffer, chat via IRC) together with server and Docker
- Publishing the repository on GitHub (only on the maintainer's explicit go)
- Automatic import of a channel's 7TV/BTTV/FFZ emote sets
- Drawing the facecam rectangle with the mouse in the dashboard
- Emojis, sound effects, campaign rules (Whop/Vyro), Discord notifications, Kick, CI

## 4. Pipeline

```
 1. Discover   Twitch API: new VODs of each configured streamer
 2. Chat       TwitchDownloaderCLI downloads the chat log (JSON, includes game chapters)
 3. Filter     keep only chapters whose game is on the streamer's list (empty list = all)
 4. Detect     chat spikes per second -> candidates with score and label
 5. Signals    download audio track -> loudness bonus; viewer clips -> bonus;
               muted segments -> candidate dropped
 6. Rank       top N above the threshold
 7. Fetch      per candidate the excerpt in best quality, with 60 s reserve on both sides
 8. Transcribe faster-whisper with word timestamps (optional)
 9. Fine cut   start and end on sentence boundaries and silence; jump cuts; zoom moment
10. Suggest    hook, title, hashtags (Claude or rules)
11. Render     ffmpeg: layout, zoom, subtitles, hook, credit, loudness
12. Dashboard  review, edit, re-render, approve or reject
13. Upload     YouTube, scheduled for the next free slot
14. Clean up   according to the retention settings
```

## 5. Highlight detection

**The chat is always the trigger, and only reactions count** (changed in milestone 1 after testing on a real stream). A reaction is a message with an emote from the lists below, spelled-out laughter ("hahaha", "xD", "lol"), question-mark spam ("???") or a hype word. Ordinary text and unlisted emotes are ignored: on a real stream the largest waves of plain messages were polls ("1"/"2"), roll calls ("YT", "Hallo") and guessing games, and unlisted emotes were mostly greetings and dancing.

Every second, the reactions in a 5 s window (burst) are compared with the level of the previous 120 s (baseline). A spike only counts if all of these hold:

- burst > baseline × multiplier (automatic: 2.5× for a small chat down to 1.5× for a large one)
- burst rate above 1 reaction per second
- robust z-score (burst − median) / (1.4826 × MAD) ≥ 4, taken on the square-root scale. On raw counts this threshold let about 45 random waves per 10 hours through in a simulated quiet chat; on the square-root scale none. The median comes from the last 120 s, the MAD from the whole stream, because 120 s are too few to estimate a spread
- at least 5 distinct viewers reacting in the window
- at most 2 reactions per user per window count
- 30 s debounce between highlights
- stream start: while less than 120 s of history exist, the level of the whole stream is used

Subscription and gift notices are dropped by their text. Quiet chats need a lower bar per streamer (`min_z`, `min_rate`).

**Reaction lists:**

| Label | Global defaults |
|---|---|
| laugh | KEKW, LUL, LULW, OMEGALUL, ICANT, pepeLaugh, plus typed laughter |
| hype | Pog, PogU, POGGERS, PogChamp, PagMan, LETSGO, EZ, W |
| shock | monkaS, monkaW, WTF, HUH, D:, NOWAY, AINTNOWAY, NotLikeThis, WutFace, plus "???" |
| words (no label) | per language, e.g. `de`: digga, bruder, alter · `en`: bro, omg, lmao · always: `!clip` |

Each streamer adds the channel's own reaction emotes. The strongest group in a spike becomes the clip's label and feeds into hook and title.

**Bonus signals** (they only change the ranking and never create a candidate on their own):
- Loudness: loud seconds inside the clip window, measured with ffmpeg on the audio track
- Viewer clips: Twitch clips created by viewers at the same position, weighted by views (official Twitch API)

**Exclusion:** a candidate whose audio Twitch has muted is dropped. Since milestone 2 this is read from the audio track itself (three or more seconds of digital silence inside the clip window) instead of the Twitch API, so it works without API keys. Dropped candidates are listed.

**Rough window:** 20 s before the spike to 8 s after it. The fine cut turns that into 15–45 s.

**Origin:** ported from clippy (`src/firehose.ts`, MIT, TypeScript) to Python are the per-user cap, the burst-against-baseline test with the adaptive multiplier `max(1.5, 2.5 − 0.1 × baseline)`, the minimum rate and the 30 s debounce, with attribution in the code and the licence text in `THIRD_PARTY_LICENSES.md`. Counting reactions only, the z-score, minimum chatters, labels and the stream-start rule are new. Nothing is taken from CTIC (GPLv3; the given URL returns 404 anyway).

## 6. Cutting and editing

### Fine cut
- Start: beginning of the sentence running at the rough start, or the last silence before it
- End: end of the sentence after the spike plus a short tail (laughter), never mid-word
- Target 15–45 s, hard limit 59 s
- Without Whisper: silence detection with ffmpeg only

### Layout

```
split                         blur (fallback without coordinates)
┌─────────────┐  0            ┌─────────────┐
│   FACECAM   │               │░ blurred ░░░│
│   1080×730  │               ├─────────────┤
├── hook ─────┤  730          │ whole frame │
│             │               │ 1080×608    │
│  GAMEPLAY   │               ├─────────────┤
│  1080×1190  │               │░ subtitles ░│
│  SUBTITLES  │  ~1270        │░░░░░░░░░░░░░│
│             │               │░░░░░░░░░░░░░│
└─────────────┘  1920         └─────────────┘
```

- `split` needs two rectangles per streamer, as relative coordinates: `facecam` and `gameplay`. `facecam_share` sets how much of the height the facecam gets (default 38 %)
- A streamer without rectangles is rendered as `blur`, which works for any stream without set-up
- **Layout check:** the dashboard shows a frame from the streamer's latest VOD with a 10 % grid and the configured rectangles drawn in, so coordinates can be read off and verified

### Subtitles
- faster-whisper with word timestamps, language per streamer; runs on CPU or GPU, whichever is available
- ASS file, burned into the video
- Montserrat Black (OFL licence, shipped with its licence text), size 84 px
- Upper case, at most 3 words per cue, punctuation dropped except `?` and `!`
- White, black outline 6 px; the current word in the highlight colour and briefly scaled to 110 %
- Position at 66 % of the height: above the lower third, clear of the TikTok/Shorts controls
- Censoring: words from the per-language list become `S***` in the text; the audio stays
- Without Whisper everything still runs, just without subtitles

### Hook
- Short text (at most 6 words) during the first 2.5 s, as a banner on the dividing line between facecam and gameplay so it does not cover the face
- Three suggestions per clip, the first preselected, editable in the dashboard
- A hook must not claim anything that does not happen in the clip

### Effects
- **Auto-zoom:** at the loudest moment the picture zooms to 112 %, holds 1.2 s and returns
- **Jump cuts:** true silence longer than 1.0 s (audio below −35 dB, not merely a pause in speech) is cut out; subtitle times are remapped. Can be turned off per clip
- **Credit:** `twitch.tv/{login}`, 60 % opacity, small on the dividing line, visible after the hook

### Output
- 1080×1920, 60 fps, H.264, `+faststart`
- Encoder `auto`: tries NVENC, AMD AMF, Intel QSV and VideoToolbox with a short test encode each and falls back to libx264 (`veryfast`, CRF 20). Can be forced in the config. Measured in milestone 3 on a 28 s gameplay clip, on a laptop with an integrated AMD GPU: libx264 8.0 s and 35 MB, AMD AMF at QP 25/27 6.0 s and 41 MB, at the same picture quality (SSIM 0.986 against a near-lossless render). Rendering is therefore far quicker than the minute per clip assumed earlier
- Audio: AAC 160 kbit/s, loudness via `loudnorm` at −14 LUFS

## 7. Dashboard

FastAPI with one plain HTML page, English, no JavaScript framework.

**List:** candidates per stream sorted by score, with label, length and status (new, approved, scheduled, live, rejected, error), plus dropped candidates with the reason.

**Clip view**
- Player with the rendered clip
- Raw excerpt player with reserve: click "Start here" and "End here" at the playback position
- Hook (three suggestions or own text), title, description, hashtags
- Subtitles editable word by word
- Layout split/blur, auto-zoom on/off, jump cuts on/off
- **Re-render** (about one minute)
- **Approve:** uploads to YouTube immediately and schedules the next free slot. Below it: "publish now" or a custom time
- **Reject**
- **Download** of the MP4 and "Copy TikTok caption", plus a tick box "posted on TikTok"

**Schedule:** overview of taken and free slots.

**Statistics:** views per uploaded clip, fetched once a day from the YouTube API.

**Layout check:** see section 6.

**Access:** default is `127.0.0.1`. With `lan: true` the dashboard is reachable in the local network, but only if a password is set in `.env`. That connection is unencrypted HTTP, so it is meant for a home network only.

## 8. Publishing

### YouTube Shorts
- YouTube Data API v3, `videos.insert`, one-time OAuth sign-in in the browser, with the user's own Google Cloud project
- Quota according to the official documentation (checked 2026-11-11): `videos.insert` has its own bucket with a default of 100 calls per day
- According to the revision history of 2026-11-02, uploads from unverified API projects are no longer locked to private. This is verified with a real upload in milestone 6
- Scheduling: upload as private with a publish time; YouTube then publishes on its own, even if the machine is off
- Slots, title template, description template and hashtags come from the config, with the placeholders `{title}`, `{streamer}`, `{login}` and `{game}`
- Category Gaming, language from the streamer entry, not "made for kids"
- **Lock:** without a permission entry or `own_channel: true` for the streamer, ClipIt refuses the upload and says why

### TikTok
No automatic upload. The dashboard provides file and caption; the user posts via tiktok.com or the app.

## 9. Operation

- **Start:** `uv run clip-it serve` starts the dashboard, the processing queue and the check for new VODs (on start, then every 30 minutes)
- **Other commands:** `clip-it doctor` checks ffmpeg, TwitchDownloaderCLI, font, keys and encoder; `clip-it process <VOD link>` processes one VOD without the dashboard
- **Data:** SQLite (`data/clip-it.db`) with VODs, candidates/clips and uploads
- **Processing:** one queue, one job at a time
- **Log:** `data/logs/clip-it.log`, rotating
- **Clean-up:** retention from the config; when the size limit is reached, the oldest raw excerpts go first
- **Platforms:** written to be portable (Python, ffmpeg and TwitchDownloaderCLI exist for Windows, Linux and macOS). v1 is developed and tested on Windows 11 only
- **Docker/server:** not in v1

## 10. Legal and security

Not legal advice; these are the rules ClipIt implements and the README states:

- Only clip streamers who have agreed in writing (e.g. via Discord), or your own channel. Per streamer the config holds date, channel and a screenshot under `data/permissions/`. Without it there is no upload. The lock prevents accidents; it cannot stop deliberate misuse
- Label paid clips as advertising according to your local rules
- No gambling campaigns
- No keys in the code: everything in `.env`, with a `.env.example` without values. `.env`, `config.yaml`, OAuth tokens and `data/` are in `.gitignore`
- AI suggestions send the clip's transcript to the Anthropic API. Without a key everything stays local
- Users are responsible for complying with the terms of Twitch, YouTube and TikTok

## 11. Architecture and folder structure

One Python package, one process, no services alongside it.

```
clip-it/
├── README.md  SPEC.md  LICENSE  THIRD_PARTY_LICENSES.md
├── pyproject.toml  config.example.yaml  .env.example  .gitignore
├── clip_it/
│   ├── cli.py          commands: doctor, process, serve
│   ├── config.py       load and validate config.yaml and .env
│   ├── db.py           SQLite
│   ├── twitch.py       Twitch API and calls to TwitchDownloaderCLI
│   ├── detect.py       read chat log, spike detection, labels
│   ├── signals.py      loudness, viewer clips, muted segments, ranking
│   ├── transcribe.py   faster-whisper (optional)
│   ├── edit.py         fine cut, jump cuts, zoom moment
│   ├── subtitles.py    ASS file, censoring
│   ├── render.py       ffmpeg filter graph
│   ├── suggest.py      hook, title, hashtags (Claude or rules)
│   ├── youtube.py      OAuth, upload, slots, statistics
│   ├── pipeline.py     steps 1–14, queue, clean-up
│   └── web/            app.py, index.html, app.js, style.css
├── assets/fonts/       Montserrat-Black.ttf + OFL.txt
├── tests/
├── config.yaml         (not in git) the user's own streamers and settings
└── data/               (not in git) database, logs, VOD data, clips, permission proofs
```

## 12. Dependencies (need the maintainer's OK)

| Package | Purpose |
|---|---|
| `fastapi`, `uvicorn` | Dashboard |
| `pyyaml` | `config.yaml` |
| `faster-whisper` | Subtitles (optional) |
| `google-api-python-client`, `google-auth-oauthlib` | YouTube upload |
| `anthropic` | AI suggestions (optional) |
| `pytest` | Tests (development only) |

**Programs:** ffmpeg, TwitchDownloaderCLI (MIT) and `uv`. streamlink only with live mode. None of them is bundled; the README explains installation.

**Deliberately not used:** `requests`, `python-dotenv`, OpenCV, numpy as a direct dependency, scheduler or queue libraries, a template engine, JavaScript frameworks. The standard library covers those needs.

**Licences:** all listed packages are MIT, BSD or Apache-2.0 and compatible with an MIT project. I confirm each one when it is added.

**Python:** `>=3.11`. Whether faster-whisper has ready-made packages for the installed 3.13.5 is checked in milestone 4; otherwise `uv` pins 3.12 for the project.

## 13. Configuration

Since milestone 1 the defaults live in `clip_it/defaults.yaml` (fully commented) and `config.example.yaml` is a short starter; a user's `config.yaml` holds only what differs. Unknown keys are reported as errors. The listing below shows the planned defaults; `emote_weight` was dropped and `min_rate: 1.0` added when detection moved to counting reactions only.

```yaml
storage:
  max_gb: 50
  keep_days: {raw_excerpts: 14, rejected: 7, uploaded: 30}

poll_minutes: 30

detect:
  burst_window_s: 5
  baseline_window_s: 120
  multiplier: auto            # 2.5 (small chat) down to 1.5 (large chat)
  min_z: 4.0
  min_chatters: 5
  max_msgs_per_user: 2
  debounce_s: 30
  emote_weight: 2.0
  pre_roll_s: 20
  post_roll_s: 8
  top_n: 8
  min_score: null             # calibrated on real chat logs in milestone 1
  emotes:
    laugh: [KEKW, LUL, LULW, OMEGALUL, ICANT, pepeLaugh, xdd, xD]
    hype:  [Pog, PogU, POGGERS, PogChamp, PagMan, LETSGO, EZ, W]
    shock: [monkaS, monkaW, WTF, HUH, "D:", NOWAY, AINTNOWAY]
  words:
    all: ["!clip"]
    de:  [digga, bruder, alter]
    en:  [bro, omg, lmao]

signals:
  audio_weight: 0.5
  viewer_clip_weight: 1.0
  skip_muted: true

clip:
  min_s: 15
  target_max_s: 45
  hard_max_s: 59
  reserve_s: 60

render:
  width: 1080
  height: 1920
  fps: 60
  encoder: auto               # or h264_nvenc, h264_amf, h264_qsv, h264_videotoolbox, libx264
  audio_kbps: 160
  loudness_lufs: -14
  zoom: {enabled: true, factor: 1.12, hold_s: 1.2}
  jump_cuts: {enabled: true, min_silence_s: 1.0, silence_db: -35}
  credit: {text: "twitch.tv/{login}", opacity: 0.6}

subtitles:
  enabled: true
  model: small
  font: Montserrat Black
  size: 84
  uppercase: true
  words_per_cue: 3
  color: "#FFFFFF"
  outline: "#000000"
  outline_px: 6
  highlight: "#FFE600"
  pop_scale: 1.10
  y_position: 0.66
  censor: {de: [], en: []}    # starter lists are shipped

hook: {duration_s: 2.5, max_words: 6}

suggest:
  provider: anthropic         # falls back to "rules" without a key

publish:
  youtube:
    timezone: Europe/Berlin
    slots: ["12:00", "15:00", "18:00", "21:00"]
    title: "{title} | {streamer} #shorts"
    description: "Clip from twitch.tv/{login}"
    hashtags: ["#twitchclips", "#shorts"]

dashboard: {host: 127.0.0.1, port: 8000, lan: false}

streamers:
  example_streamer:           # the Twitch login name
    display_name: Example Streamer
    language: en
    games: []                 # empty = all games
    own_channel: false
    permission: {date: null, via: null, proof: null}
    layout:
      default: blur           # "split" needs the two rectangles below
      # facecam_share: 0.38
      # facecam:  {x: 0.0, y: 0.0, w: 0.0, h: 0.0}
      # gameplay: {x: 0.0, y: 0.0, w: 0.0, h: 0.0}
    emotes: {laugh: [], hype: [], shock: []}
    hashtags: []
```

`.env`: `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `ANTHROPIC_API_KEY`, `DASHBOARD_PASSWORD`. The Google OAuth file lives under `data/`.

## 14. Tests

**pytest**
- Detection with a synthetic chat log in TwitchDownloader format: several hype moments are found; a single spammer and normal chat noise produce no highlights; no false alarm at stream start
- Fine cut (sentence boundaries), remapping of subtitle times for jump cuts
- Subtitles (word groups, censoring)
- Slot scheduling, upload lock without permission, config validation, fallback to `blur` without rectangles

**Rendering**
- A test video from `ffmpeg testsrc` plus a test tone through both layouts
- `ffprobe` checks 1080×1920, 60 fps, H.264/AAC and length
- I extract single frames and check layout, subtitles, hook and credit by eye

**Real material:** one real VOD, local only.

## 15. Milestones

After each milestone I show the result and ask whether to continue. The days are a target plan; it only holds if approvals and credentials arrive promptly.

| # | Target | Content | Acceptance |
|---|---|---|---|
| 1 | Wed 11 – Thu 12 Nov | Project skeleton, licence, config, `doctor`, chat log reader, spike detection, labels | Tests green; candidate list for a real VOD |
| 2 | Fri 13 Nov | Twitch API (VODs, muted segments, viewer clips), game filter, audio loudness, ranking, excerpt download | Top-8 excerpts of one VOD are in the folder |
| 3 | Sat 14 Nov | Rendering: split and blur, credit, loudness, encoder probing, layout check | Test video frames checked; one real clip without subtitles |
| 4 | Sun 15 Nov | Transcript, fine cut, subtitles, censoring, hook, AI suggestions, auto-zoom | Finished clips via `clip-it process` |
| 5 | Mon 16 Nov | Dashboard: list, clip view, re-trimming, corrections, re-render, download, LAN access | A clip is approved in the browser |
| 6 | Tue 17 Nov | YouTube: OAuth, upload, slots, lock, schedule view | Private test upload of a test video |
| 7 | Wed 18 Nov | Automation, clean-up, statistics, README, dress rehearsal; jump cuts if time allows | Full run on a fresh VOD |

**Credentials the maintainer creates** (the README explains each): Twitch developer app before milestone 2, Anthropic API key before milestone 4, Google Cloud project and YouTube channel before milestone 6.

**Publishing on GitHub** is a separate step after v1 and happens only on the maintainer's explicit go, after a check that no secrets or personal data are in the history.

## 16. Open points and risks

**Open**
1. Register "clip-it" on PyPI before publishing a package (the name was free on 2026-11-12)

**Risks**
1. **Muted VOD passages:** Twitch mutes passages with music, often in games with licensed music. Good moments can be lost. Only live mode would help
2. **Music in the clip:** game music that is not muted can trigger copyright claims on YouTube and TikTok
3. **Schedule:** seven milestones in eight days is tight, and the open-source requirements add a little work. Jump cuts slip first
4. **Tested on one machine:** v1 is verified on Windows 11 with an AMD GPU. NVENC, QSV, VideoToolbox, Linux and macOS are written to work but untested until someone runs them
5. **Game chapters** come from TwitchDownloaderCLI's chat log, not from the official API. Whether the field is reliably present is checked in milestone 1. Fallback: a manual time range.
6. **TwitchDownloaderCLI** depends on Twitch internals and can break after Twitch changes until an update appears. The exact commands (audio only, partial download) are checked in milestone 2
7. **Facecam sharpness:** a small facecam is enlarged a lot in `split` (for example from 460 px to 1080 px) and looks soft. Way out: a smaller `facecam_share`
8. **Layout changes:** fixed coordinates go stale when a streamer changes the stream layout. One config value is adjusted then
9. **Whisper:** slang and names are misheard more often, hence the correction in the dashboard. Speed and model size on CPU are measured in milestone 4
10. **YouTube:** new channels have their own upload limits and partly need phone verification. To my knowledge, Google sign-ins of apps in testing mode expire after 7 days; both are clarified in milestone 6. Whether a pure clip channel gets monetised is decided by YouTube under its reused-content rules
11. **Age restriction:** mature streams and violent games can get individual clips age-restricted

## 17. Defaults I set without asking

Tell me if one does not fit:

- MIT as the licence
- English only for dashboard and README (no German version)
- `config.yaml` stays out of git; the repository ships `config.example.yaml`
- Yellow `#FFE600` as the default highlight colour
- `own_channel: true` as a second way to unlock uploads, for streamers clipping themselves
- `blur` as the fallback layout when a streamer has no rectangles
- Hook as a banner on the dividing line rather than at the very top, so the face stays free
- Facecam share 38 %, gameplay as the centre crop
- Subtitles 84 px at 66 % of the height, at most 3 words
- Loudness −14 LUFS, audio 160 kbit/s
- Slots at 12:00, 15:00, 18:00 and 21:00
- Viewer clips and loudness only give bonus points and never create a candidate on their own
- Jump cuts only remove true silence, not pauses in speech with game sound
- Test uploads are always private
