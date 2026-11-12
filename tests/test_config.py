"""Config loading: defaults, user overrides, per-streamer settings, .env."""
import os
from pathlib import Path

import pytest
import yaml

from clip_it.config import ConfigError, build_config, detect_settings, load_config, load_env

ROOT = Path(__file__).parent.parent


def test_defaults_apply_when_the_user_sets_nothing():
    cfg = build_config({})

    assert cfg["detect"]["min_z"] == 4.0
    assert cfg["streamers"] == {}


def test_user_value_overrides_default_and_keeps_the_rest():
    cfg = build_config({"detect": {"top_n": 3}})

    assert cfg["detect"]["top_n"] == 3
    assert cfg["detect"]["debounce_s"] == 30


def test_unknown_setting_is_reported_with_its_path():
    with pytest.raises(ConfigError, match="detect.debouce_s"):
        build_config({"detect": {"debouce_s": 10}})


def test_non_numeric_threshold_is_rejected():
    with pytest.raises(ConfigError, match="min_z"):
        build_config({"detect": {"min_z": "four"}})


def test_streamer_gets_defaults_and_login_as_display_name():
    cfg = build_config({"streamers": {"someone": {}}})

    assert cfg["streamers"]["someone"]["display_name"] == "someone"
    assert cfg["streamers"]["someone"]["language"] == "en"
    assert cfg["streamers"]["someone"]["games"] == []


def test_streamer_login_is_lowercased():
    cfg = build_config({"streamers": {"SomeOne": {}}})

    assert list(cfg["streamers"]) == ["someone"]


def test_typo_in_streamer_entry_is_reported():
    with pytest.raises(ConfigError, match="streamers.a.langauge"):
        build_config({"streamers": {"a": {"langauge": "de"}}})


def test_streamer_detect_override_only_affects_that_streamer():
    cfg = build_config({"streamers": {"a": {"detect": {"min_z": 6}}, "b": {}}})

    assert detect_settings(cfg, "a")["min_z"] == 6
    assert detect_settings(cfg, "b")["min_z"] == 4.0


def test_streamer_emotes_and_language_words_are_added_to_the_global_lists():
    cfg = build_config(
        {"streamers": {"a": {"language": "de", "emotes": {"laugh": ["HAH"]}, "words": ["Junge"]}}}
    )

    settings = detect_settings(cfg, "a")

    assert {"KEKW", "HAH"} <= settings["emotes"]["laugh"]
    assert {"!clip", "digga", "junge"} <= settings["words"]
    assert "bro" not in settings["words"]  # English list is not used for a German streamer


def test_example_config_is_valid():
    example = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))

    cfg = build_config(example)

    assert cfg["streamers"]


def test_missing_config_file_explains_what_to_do(tmp_path):
    with pytest.raises(ConfigError, match="config.example.yaml"):
        load_config(tmp_path / "config.yaml")


def test_load_env_reads_keys_without_overriding_existing_ones(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# comment\nCLIPIT_TEST_A=from-file\nCLIPIT_TEST_B="quoted"\n', encoding="utf-8"
    )
    monkeypatch.setenv("CLIPIT_TEST_A", "already-set")
    monkeypatch.setenv("CLIPIT_TEST_B", "placeholder")
    monkeypatch.delenv("CLIPIT_TEST_B")

    load_env(env_file)

    assert os.environ["CLIPIT_TEST_A"] == "already-set"
    assert os.environ["CLIPIT_TEST_B"] == "quoted"
