"""Suggestions for a clip's hook and title.

Rule-based for now: three stock hooks per label and language. They talk about
the chat's reaction, which is the one thing ClipIt knows to be true about a
highlight, so a hook never promises something the clip does not show.
"""
from __future__ import annotations

_HOOKS = {
    "de": {
        "laugh": ["Der Chat lacht sich kaputt", "Der Chat kann nicht mehr", "Zu lustig für den Chat"],
        "hype": ["Der Chat rastet aus", "Der Chat feiert das", "Was für ein Moment"],
        "shock": ["Der Chat ist geschockt", "Damit hat keiner gerechnet", "Der Chat kann es nicht fassen"],
        None: ["Der Chat dreht durch", "Das musst du sehen", "Was für ein Moment"],
    },
    "en": {
        "laugh": ["Chat is dying of laughter", "Chat can't breathe", "Too funny for chat"],
        "hype": ["Chat goes wild", "Chat loves this", "What a moment"],
        "shock": ["Chat is shocked", "Nobody saw this coming", "Chat can't believe it"],
        None: ["Chat loses it", "You have to see this", "What a moment"],
    },
}


def suggest(label: str | None, language: str) -> dict:
    """Three hook texts and a title for a highlight with this label."""
    by_label = _HOOKS.get(language, _HOOKS["en"])
    hooks = by_label.get(label, by_label[None])
    return {"hooks": list(hooks), "title": hooks[0]}
