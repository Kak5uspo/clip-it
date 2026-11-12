# ClipIt

Finds highlights in the Twitch VODs of any streamer you configure, cuts and
edits them into vertical clips, and lets you review them before anything is
published.

> **Status: work in progress.** So far ClipIt finds the highlights of a VOD
> and downloads the matching excerpts. Cutting, subtitles, the dashboard and
> the YouTube upload follow; see [SPEC.md](SPEC.md) for the plan.

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python and the dependencies)
- [ffmpeg](https://ffmpeg.org/download.html)
- [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader/releases),
  on your `PATH` or in a `tools` folder inside the project

## Setup

```bash
uv sync
```

Copy `config.example.yaml` to `config.yaml` and `.env.example` to `.env`, then
fill in your streamers and keys. Both files stay on your machine.

Check that everything is in place:

```bash
uv run python -m clip_it doctor
```

### Twitch API keys

Needed for finding new VODs and for viewer clips (not for `process` below).

1. Open <https://dev.twitch.tv/console> and log in. Twitch requires
   two-factor authentication on the account.
2. Choose **Register Your Application**. Name: anything unique. OAuth Redirect
   URL: `http://localhost`. Category: Application Integration. Client type:
   Confidential.
3. Open the new application with **Manage**, copy the **Client ID**, create a
   **New Secret** and copy it.
4. Put both into `.env` as `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`.

## Usage

Process one VOD, given its id or link:

```bash
uv run python -m clip_it process https://www.twitch.tv/videos/<VOD id>
```

This downloads the chat log, finds the highlights, measures the loudness of
the audio track, ranks the highlights, downloads the best ones as video
excerpts (with a minute of reserve on both sides) and renders each as a
vertical 1080x1920 clip. Everything lands in `data/vods/<VOD id>/`, with a
`candidates.json` describing each clip. Highlights whose audio Twitch has
muted are skipped and listed. Running the command again reuses what is
already downloaded.

### Subtitles and fine cut

Subtitles need the optional speech recognition:

```bash
uv sync --extra subtitles
```

With it, ClipIt transcribes each highlight, moves the start and end of the
clip onto sentence boundaries (15 to 45 seconds, never more than 59) and burns
in subtitles: three words at a time, the spoken word highlighted, words from
your `subtitles.censor` list shown as `S***`. A short hook text sits in the
picture for the first seconds. Without the extra, clips are the rough window
from 20 seconds before the chat reacts to 8 seconds after, without subtitles.

`subtitles.model` picks the Whisper model. On an 8-core laptop CPU, 50 seconds
of speech took 10 seconds with `small` and 82 seconds with `medium`; `medium`
got slang and punctuation noticeably better. The model is downloaded on first
use (about 0.5 GB for `small`, 1.5 GB for `medium`).

### Hook, title and hashtags

With an [Anthropic API key](https://console.anthropic.com) in `.env` as
`ANTHROPIC_API_KEY` and the optional extra installed, Claude writes three
hooks, a title and hashtags for every clip from its transcript:

```bash
uv sync --extra ai
```

Each clip costs a fraction of a cent. The transcript is sent to the Anthropic
API for this. Without a key, or if a request fails, ClipIt uses stock texts
that describe the chat's reaction ("Chat is dying of laughter"). Set
`suggest.provider: rules` to always use those.

On Windows, keep the project in a folder with a short path. Tools that nest
their files deeply can hit the 260-character path limit otherwise.

### Layouts

- `blur` (default): the whole stream picture in the middle, over a blurred
  copy of itself. Works for every stream without any set-up.
- `split`: facecam on top, gameplay below. Needs two rectangles per streamer,
  given as fractions of the stream picture:

```yaml
streamers:
  example_streamer:
    layout: split
    facecam:  {x: 0.76, y: 0.19, w: 0.24, h: 0.30}
    gameplay: {x: 0.25, y: 0.0,  w: 0.50, h: 1.0}
```

To find and verify the numbers, draw them onto a frame of the stream:

```bash
uv run python -m clip_it layout-check data/vods/<VOD id>/excerpt_<n>.mp4 --streamer example_streamer
```

The picture `data/layout_check_<streamer>.png` shows a grid with lines every
10 % (so the third line from the left is x = 0.3), the facecam rectangle in
yellow and the gameplay rectangle in cyan.

To only look at what the detection finds in a chat log you already have:

```bash
uv run python -m clip_it detect data/vods/<VOD id>/chat.json
```

All detection settings and their defaults are documented in
[clip_it/defaults.yaml](clip_it/defaults.yaml). Override the ones you want
to change in your `config.yaml`, globally or per streamer.

### Tuning detection

A highlight is a burst of *reactions*: listed emotes, typed laughter
("hahaha", "xD", "lol"), "???" or hype words. Ordinary text does not count.

- **Add your channel's reaction emotes** under `emotes` (`laugh`, `hype`,
  `shock`). Without them, a chat that reacts with its own emotes looks silent.
- **Quiet chat, few highlights?** Lower `detect.min_z` and `detect.min_rate`
  for that streamer. The defaults ask for about 8 reactions within 5 seconds.
- `detect` prints the chapters of a stream, so you can copy the exact game
  names for the `games` filter.

## Tests

```bash
uv run pytest
```

## Rules of use

- Only clip streamers who have agreed in writing, or your own channel.
- Label paid clips as advertising according to your local rules.
- No gambling campaigns.
- You are responsible for complying with the terms of Twitch, YouTube and TikTok.

## Licence

[MIT](LICENSE). The spike detection is partly ported from
[clippy](https://github.com/hamzaskewl/clippy); see
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
