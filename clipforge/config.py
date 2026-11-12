"""Load config.yaml (merged over the built-in defaults) and .env."""
from __future__ import annotations

import copy
import os
from numbers import Real
from pathlib import Path

import yaml

DEFAULTS = yaml.safe_load((Path(__file__).parent / "defaults.yaml").read_text(encoding="utf-8"))

# Mappings whose keys the user chooses freely (labels, language codes).
_OPEN = ("emotes", "words")


class ConfigError(Exception):
    """A problem in config.yaml that the user has to fix."""


def _mapping(value, where: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"'{where}' must be a mapping, not {type(value).__name__}")
    return dict(value)


def _merge(base: dict, over: dict, path: str = "", open_: bool = False) -> dict:
    """Return `base` updated with `over`. A key that `base` lacks is a typo."""
    out = copy.deepcopy(base)
    for key, value in over.items():
        where = f"{path}.{key}" if path else str(key)
        if key not in base and not open_:
            raise ConfigError(f"Unknown setting '{where}' in config.yaml")
        if isinstance(base.get(key), dict):
            out[key] = _merge(base[key], _mapping(value, where), where, key in _OPEN)
        else:
            out[key] = value
    return out


def _check(section_name: str, section: dict, path: str) -> None:
    """Reject values of the wrong kind in one section (detect, signals, clip)."""
    for key, default in DEFAULTS[section_name].items():
        value = section[key]
        number = isinstance(value, Real) and not isinstance(value, bool)
        if isinstance(default, dict):
            continue
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif key != "multiplier" and isinstance(default, str):
            ok = isinstance(value, str)
        elif key == "multiplier":
            ok = value == "auto" or (number and value > 0)
        elif key == "min_score":
            ok = value is None or number
        elif key.endswith("_window_s"):
            ok = isinstance(value, int) and value >= 1
        else:
            ok = number and (value >= 0 or default < 0)  # only loudness targets are negative
        if not ok:
            raise ConfigError(f"'{path}.{key}' has an invalid value: {value!r}")


def _check_layout(streamer: dict, path: str) -> None:
    if streamer["layout"] not in ("split", "blur"):
        raise ConfigError(f"'{path}.layout' must be split or blur, not {streamer['layout']!r}")
    share = streamer["facecam_share"]
    if not isinstance(share, Real) or isinstance(share, bool) or not 0.1 <= share <= 0.9:
        raise ConfigError(f"'{path}.facecam_share' must be between 0.1 and 0.9")
    for key in ("facecam", "gameplay"):
        rect = streamer[key]
        if rect is None:
            continue
        numbers = isinstance(rect, dict) and set(rect) == {"x", "y", "w", "h"} and all(
            isinstance(v, Real) and not isinstance(v, bool) for v in rect.values()
        )
        if not numbers or min(rect.values()) < 0 or rect["w"] == 0 or rect["h"] == 0 \
                or rect["x"] + rect["w"] > 1 or rect["y"] + rect["h"] > 1:
            raise ConfigError(
                f"'{path}.{key}' must be {{x, y, w, h}} as fractions of the picture (0 to 1) that stay inside it"
            )


def build_config(user: dict | None) -> dict:
    """Merge the user's settings over the defaults and validate them."""
    user = _mapping(user, "config.yaml")
    entries = _mapping(user.pop("streamers", None), "streamers")
    cfg = _merge(DEFAULTS, user)
    for section in ("detect", "signals", "clip", "render"):
        _check(section, cfg[section], section)
    for login, entry in entries.items():
        login = str(login).lower()
        path = f"streamers.{login}"
        entry = _mapping(entry, path)
        overrides = _mapping(entry.pop("detect", None), f"{path}.detect")
        streamer = _merge(cfg["streamer_defaults"], entry, path)
        streamer["display_name"] = streamer["display_name"] or login
        _check_layout(streamer, path)
        streamer["detect"] = _merge(cfg["detect"], overrides, f"{path}.detect")
        _check("detect", streamer["detect"], f"{path}.detect")
        cfg["streamers"][login] = streamer
    return cfg


def load_config(path: str | Path = "config.yaml") -> dict:
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"{path} not found. Copy config.example.yaml to config.yaml and add your streamers."
        )
    try:
        user = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise ConfigError(f"{path} is not valid YAML: {err}") from err
    return build_config(user)


def detect_settings(cfg: dict, login: str) -> dict:
    """Detection settings for one streamer: thresholds plus merged emote and word sets."""
    if login not in cfg["streamers"]:
        known = ", ".join(cfg["streamers"]) or "none"
        raise ConfigError(f"No streamer '{login}' in config.yaml (configured: {known}). Use --streamer LOGIN.")
    streamer = cfg["streamers"][login]
    settings = dict(streamer["detect"])
    lists, own = settings["emotes"], streamer["emotes"]
    settings["emotes"] = {
        label: {str(e) for e in [*(lists.get(label) or []), *(own.get(label) or [])]}
        for label in dict.fromkeys([*lists, *own])  # keeps the order; ties go to the first label
    }
    words = settings["words"]
    settings["words"] = {
        str(w).lower()
        for w in [*(words.get("all") or []), *(words.get(streamer["language"]) or []), *streamer["words"]]
    }
    settings["games"] = [str(g) for g in streamer["games"]]
    return settings


def load_env(path: str | Path = ".env") -> None:
    """Put KEY=VALUE lines from .env into the environment; existing variables win."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
