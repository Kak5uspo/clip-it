"""Downloads through TwitchDownloaderCLI."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

TOOL = "TwitchDownloaderCLI"
INSTALL_HINT = "put it on PATH or into ./tools: https://github.com/lay295/TwitchDownloader/releases"


class ToolError(Exception):
    """An external program is missing or failed."""


def find_tool(name: str) -> str | None:
    """Path of an external program, looked up on PATH and in ./tools."""
    return shutil.which(name) or shutil.which(name, path="tools")


def vod_id(reference: str) -> str:
    """The numeric id from a VOD id or a twitch.tv/videos/... link."""
    match = re.fullmatch(r"(?:.*/videos/)?(\d+)/?(?:\?.*)?", reference.strip())
    if not match:
        raise ValueError(f"Not a Twitch VOD id or link: {reference}")
    return match.group(1)


def _run(command: str, out: Path, *args: str) -> None:
    tool = find_tool(TOOL)
    if not tool:
        raise ToolError(f"{TOOL} not found; {INSTALL_HINT}")
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [tool, command, *args, "-o", str(out), "--collision", "Overwrite", "--banner", "false",
         "--log-level", "Warning,Error"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0 or not out.exists():
        detail = (result.stderr or result.stdout).strip()[-500:]
        raise ToolError(f"{TOOL} {command} failed: {detail or 'no output file was written'}")


def download_chat(vod: str, out: Path) -> None:
    _run("chatdownload", out, "--id", vod)


def download_audio(vod: str, out: Path, start: float, end: float) -> None:
    _run("videodownload", out, "--id", vod, "-q", "Audio Only", "-b", f"{int(start)}s", "-e", f"{int(end)}s")


def download_excerpt(vod: str, out: Path, start: float, end: float) -> None:
    """Video in the best available quality."""
    _run("videodownload", out, "--id", vod, "-b", f"{int(start)}s", "-e", f"{int(end)}s")
