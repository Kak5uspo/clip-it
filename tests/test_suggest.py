"""Rule-based suggestions for hook and title."""
from clip_it.suggest import suggest


def test_three_short_hooks_in_the_streamers_language_matching_the_label():
    german, english = suggest("laugh", "de"), suggest("laugh", "en")

    assert len(german["hooks"]) == 3 and len(set(german["hooks"])) == 3
    assert all(len(hook.split()) <= 6 for hook in german["hooks"] + english["hooks"])
    assert german["hooks"] != english["hooks"]
    assert german["hooks"] != suggest("shock", "de")["hooks"]


def test_the_title_is_the_first_hook():
    suggestion = suggest("hype", "de")

    assert suggestion["title"] == suggestion["hooks"][0]


def test_unknown_label_and_language_still_get_a_suggestion():
    assert len(suggest(None, "fr")["hooks"]) == 3


def test_without_an_api_key_the_rules_are_used(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = {"provider": "anthropic", "model": "claude-opus-5-5"}

    suggestion = suggest("laugh", "de", "Ach du Scheiße, ich hab F gedrückt", "Someone", None, settings)

    assert suggestion["source"] == "rules"
    assert suggestion["hooks"][0] == "Der Chat lacht sich kaputt"


def test_a_failing_request_falls_back_to_the_rules(monkeypatch):
    import clip_it.suggest as module

    def broken(*args):
        raise RuntimeError("service unavailable")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    monkeypatch.setattr(module, "_ask_claude", broken)  # no network call in tests

    suggestion = suggest("shock", "de", "Was war das denn", "Someone", None, {"provider": "anthropic"})

    assert suggestion["source"] == "rules"
