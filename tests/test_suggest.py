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
