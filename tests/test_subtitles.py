"""Subtitles: grouping words into cues, censoring, and the ASS file."""
from clip_it.config import build_config
from clip_it.subtitles import Word, build_ass, censor, cues

STYLE = build_config({})["subtitles"]


def words(*texts, start=1.0, each=0.3):
    """Words spoken back to back, `each` seconds long."""
    return [Word(start + i * each, start + (i + 1) * each, text) for i, text in enumerate(texts)]


def dialogue_lines(ass):
    return [line for line in ass.splitlines() if line.startswith("Dialogue:")]


def test_words_are_shown_three_at_a_time():
    groups = cues(words("das", "war", "ja", "wirklich", "komplett", "irre", "heute"), max_words=3)

    assert [[w.text for w in group] for group in groups] == [
        ["das", "war", "ja"], ["wirklich", "komplett", "irre"], ["heute"],
    ]


def test_a_pause_starts_a_new_cue():
    spoken = words("nein", "nein") + words("doch", start=4.0)

    groups = cues(spoken, max_words=3)

    assert [[w.text for w in group] for group in groups] == [["nein", "nein"], ["doch"]]


def test_the_end_of_a_sentence_starts_a_new_cue():
    groups = cues(words("was?", "nein", "wirklich"), max_words=3)

    assert [[w.text for w in group] for group in groups] == [["was?"], ["nein", "wirklich"]]


def test_censor_keeps_the_first_letter_and_ignores_case_and_punctuation():
    banned = {"scheiße", "mist"}

    assert censor("Scheiße!", banned) == "S******!"
    assert censor("MIST", banned) == "M***"
    assert censor("Mistgabel", banned) == "Mistgabel"  # only whole words


def test_every_word_gets_its_own_moment_with_the_spoken_word_highlighted():
    ass = build_ass(words("das", "war", "irre"), STYLE)

    lines = dialogue_lines(ass)
    assert len(lines) == 3
    assert lines[0].startswith("Dialogue: 0,0:00:01.00,0:00:01.30,Sub,")
    assert lines[1].startswith("Dialogue: 0,0:00:01.30,0:00:01.60,Sub,")
    # In the second line all three words are shown and only "WAR" is highlighted.
    second = lines[1]
    between_das_and_war = second.split("WAR")[0].rsplit("DAS", 1)[1]
    assert "\\c&H" in between_das_and_war
    assert second.count("\\c&H") == 1
    assert second.rstrip().endswith("IRRE")


def test_text_is_upper_case_without_commas_and_full_stops_but_keeps_question_marks():
    ass = build_ass(words("Ja,", "klar.", "Oder?"), STYLE)

    text = " ".join(dialogue_lines(ass))
    assert "JA" in text and "KLAR" in text and "ODER?" in text
    assert "JA," not in text and "KLAR." not in text


def test_banned_words_are_censored_in_the_subtitles():
    style = {**STYLE, "censor": {"de": ["mist"]}}

    ass = build_ass(words("so", "ein", "Mist"), style, language="de")

    assert "M***" in ass
    assert "MIST" not in ass


def test_the_file_is_laid_out_for_a_vertical_1080p_picture_with_the_bundled_font():
    ass = build_ass(words("hallo"), STYLE)

    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Style: Sub,Montserrat Black,84," in ass
    assert "\\pos(540,1267)" in ass  # 66 % of the height


def test_the_highlight_colour_comes_from_the_settings():
    ass = build_ass(words("hallo"), {**STYLE, "highlight": "#FF2E97"})

    assert "\\c&H972EFF&" in ass  # ASS writes colours as blue-green-red


def test_the_hook_is_shown_for_the_first_seconds_at_the_given_height():
    ass = build_ass(words("hallo"), STYLE, hook="Er rastet aus", hook_y=730)

    (hook,) = [line for line in dialogue_lines(ass) if ",Hook," in line]
    assert hook.startswith("Dialogue: 1,0:00:00.00,0:00:02.50,Hook,")
    assert "\\pos(540,730)" in hook and "ER RASTET AUS" in hook


def test_without_words_there_are_no_subtitle_lines_but_a_hook_still_works():
    ass = build_ass([], STYLE, hook="Schau dir das an", hook_y=730)

    assert [",Hook," in line for line in dialogue_lines(ass)] == [True]


def test_words_without_duration_get_no_line_of_their_own():
    # Whisper sometimes returns a word whose start equals its end; ffmpeg then
    # drops other lines of the file, such as the hook.
    spoken = [Word(1.0, 1.4, "ach"), Word(1.4, 1.4, "du"), Word(1.4, 1.9, "scheiße")]

    ass = build_ass(spoken, STYLE, hook="Hook", hook_y=730)

    for line in dialogue_lines(ass):
        start, end = line.split(",")[1:3]
        assert start != end
    assert sum(",Sub," in line for line in dialogue_lines(ass)) == 2
