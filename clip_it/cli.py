"""Command line: `python -m clip_it <command>`."""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

from .config import ConfigError, detect_settings, load_config, load_env
from .detect import detect, read_chat
from .pipeline import process
from .render import layout_check, layout_for
from .twitch import INSTALL_HINT, TOOL, ToolError, find_tool
from .youtube import TOKEN, UploadRefused

_TABLE = " #      time   score  react/s  normal  viewers  label   game"


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _row(rank: int, h: dict) -> str:
    return (
        f"{rank:>2}  {_clock(h['spike_s']):>8}  {h['score']:>6.1f}  {h['rate']:>7.1f}  {h['baseline']:>6.1f}"
        f"  {h['chatters']:>7}  {h['label'] or '-':<6}  {h['game'] or '-'}"
    )


def cmd_doctor(args: argparse.Namespace) -> int:
    problems = 0

    def report(name: str, ok: bool, detail: str = "") -> None:
        nonlocal problems
        problems += not ok
        print(f"[{'ok' if ok else 'MISSING'}] {name}{': ' + detail if detail else ''}")

    report("Python 3.11+", sys.version_info >= (3, 11), platform.python_version())
    for tool, hint in (
        ("ffmpeg", "https://ffmpeg.org/download.html"),
        ("ffprobe", "ships with ffmpeg"),
        (TOOL, INSTALL_HINT),
    ):
        path = find_tool(tool)
        report(tool, bool(path), path or hint)
    try:
        streamers = load_config()["streamers"]
        report("config.yaml", bool(streamers), ", ".join(streamers) or "no streamers configured")
    except ConfigError as err:
        report("config.yaml", False, str(err))
    report("YouTube sign-in", TOKEN.exists(), str(TOKEN) if TOKEN.exists() else "run: uv run python -m clip_it youtube-login")
    for key in ("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"):
        is_set = bool(os.environ.get(key))
        report(key, is_set, "set" if is_set else "add it to .env (see .env.example)")
    print("Everything is in place." if not problems else f"{problems} thing(s) to fix.")
    return 1 if problems else 0


def cmd_detect(args: argparse.Namespace) -> int:
    cfg = load_config()
    chat = read_chat(args.chat)
    settings = detect_settings(cfg, (args.streamer or chat.streamer).lower())
    if settings["games"] and not chat.chapters:
        print("Warning: the chat log has no game chapters, so the game filter is ignored.", file=sys.stderr)
    highlights = detect(chat, settings)[: settings["top_n"]]

    print(chat.title or args.chat)
    print(f"{_clock(chat.duration)} long, {len(chat.messages)} messages")
    for chapter in chat.chapters:
        print(f"  chapter {_clock(chapter.start)}  {chapter.game}")
    print(f"\n{len(highlights)} highlight{'' if len(highlights) == 1 else 's'}")
    if highlights:
        print(_TABLE)
    for rank, h in enumerate(highlights, 1):
        print(_row(rank, vars(h)))
    return 0


def cmd_process(args: argparse.Namespace) -> int:
    summary = process(args.vod, load_config(), args.streamer, redo=args.redo)
    print(f"\n{summary['title']}")
    print(f"{len(summary['candidates'])} clip(s) in {summary['folder']}")
    if summary["candidates"]:
        print(_TABLE + "  clip")
    for c in summary["candidates"]:
        print(f"{_row(c['rank'], c)}  {c['clip']}")
    for h in summary["dropped_muted"]:
        print(f"dropped, audio muted by Twitch: {_clock(h['spike_s'])} (score {h['score']})")
    return 0


def cmd_layout_check(args: argparse.Namespace) -> int:
    cfg = load_config()
    login = args.streamer.lower()
    detect_settings(cfg, login)  # reports an unknown streamer
    out = Path("data") / f"layout_check_{login}.png"
    layout_check(Path(args.video), out, cfg["streamers"][login], args.at)
    print(f"Layout '{layout_for(cfg['streamers'][login])}'. Check picture: {out}")
    print("Yellow = facecam, cyan = gameplay; the grid lines are 10 % apart.")
    return 0


def cmd_youtube_login(args: argparse.Namespace) -> int:
    from . import youtube

    youtube.login()
    print(f"Signed in. The token is stored in {youtube.TOKEN}; keep it private.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import socket

    import uvicorn

    from .web.app import create_app

    cfg = load_config()
    lan, port = cfg["dashboard"]["lan"], cfg["dashboard"]["port"]
    password = os.environ.get("DASHBOARD_PASSWORD") or None
    if lan and not password:
        raise ConfigError("dashboard.lan is on, so set DASHBOARD_PASSWORD in .env first.")
    print(f"ClipIt dashboard: http://127.0.0.1:{port}")
    if lan:
        print(f"In your network: http://{socket.gethostbyname(socket.gethostname())}:{port} (any user name, your password)")
    print("Stop with Ctrl+C.")
    uvicorn.run(create_app(cfg, password=password if lan else None), host="0.0.0.0" if lan else "127.0.0.1",
                port=port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # stream titles with emoji on a legacy console
    parser = argparse.ArgumentParser(
        prog="clip-it", description="Find highlights in Twitch VODs and turn them into vertical clips."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="check that tools, config and keys are in place")
    detect_parser = commands.add_parser("detect", help="list the highlights found in a downloaded chat log")
    detect_parser.add_argument("chat", help="chat log (JSON) written by TwitchDownloaderCLI")
    process_parser = commands.add_parser("process", help="find a VOD's highlights and download their excerpts")
    process_parser.add_argument("vod", help="VOD id or twitch.tv/videos/... link")
    process_parser.add_argument("--redo", action="store_true", help="make every clip again, dropping edits and status")
    for sub in (detect_parser, process_parser):
        sub.add_argument("--streamer", help="config entry to use (default: the streamer named in the chat log)")
    layout_parser = commands.add_parser(
        "layout-check", help="draw a streamer's facecam and gameplay rectangles onto a video frame"
    )
    layout_parser.add_argument("video", help="any video file of the stream, e.g. a downloaded excerpt")
    layout_parser.add_argument("--streamer", required=True, help="config entry whose rectangles to draw")
    layout_parser.add_argument("--at", type=float, default=0.0, help="second of the video to take the frame from")
    commands.add_parser("serve", help="open the review dashboard in your browser")
    commands.add_parser("youtube-login", help="sign in to YouTube once, for uploads")
    args = parser.parse_args(argv)

    load_env()
    handlers = {"doctor": cmd_doctor, "detect": cmd_detect, "process": cmd_process, "layout-check": cmd_layout_check,
                "serve": cmd_serve, "youtube-login": cmd_youtube_login}
    try:
        return handlers[args.command](args)
    except ConfigError as err:
        print(f"Config error: {err}", file=sys.stderr)
    except (ToolError, ValueError, OSError, json.JSONDecodeError, UploadRefused) as err:
        print(f"Error: {err}", file=sys.stderr)
    return 2
