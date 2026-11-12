"""The command line, driven through main() the way a user would call it."""
from clipforge.cli import main
from test_detect import ChatLog


def test_detect_command_lists_the_highlights_of_a_chat_log(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("streamers:\n  test:\n    language: de\n", encoding="utf-8")
    log = ChatLog(3600)
    log.noise(1.0)
    log.burst(600)

    exit_code = main(["detect", str(log.write(tmp_path))])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "1 highlight" in out
    assert "0:09:5" in out  # the burst at 600 s; the chat starts to react a few seconds earlier
    assert "laugh" in out


def test_detect_command_explains_an_unknown_streamer(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("streamers:\n  someone_else: {}\n", encoding="utf-8")
    log = ChatLog(60)

    exit_code = main(["detect", str(log.write(tmp_path))])

    assert exit_code == 2
    assert "--streamer" in capsys.readouterr().err


def test_doctor_fails_and_says_what_to_do_without_a_config(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    exit_code = main(["doctor"])

    assert exit_code == 1
    assert "config.example.yaml" in capsys.readouterr().out
