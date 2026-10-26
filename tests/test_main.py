import pytest

from gentle_stream import main
from tests.test_daemon import runtime  # noqa: F401  (fixture: private runtime dir, fake audio, cleanup)


def test_help_lists_flags_and_controls(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    out = capsys.readouterr().out
    assert exit_info.value.code == 0
    for text in ("--model", "--mood", "--gentle-shell", "play / pause", "next piece", "describe a mood",
                 "save what is playing", "saved prompts", "presets.json", "the music keeps playing",
                 "quit and stop the music", "ctl", "play|pause|toggle|next|stop|status"):
        assert text in out
    assert "daemon" not in out                     # started automatically, never by hand


def test_an_unavailable_audio_output_is_a_clean_error(runtime, monkeypatch, capsys):
    monkeypatch.setenv("GENTLE_STREAM_AUDIO_FACTORY", "tests.test_daemon:no_device")
    assert main([]) == 1
    err = capsys.readouterr().err
    assert err == "gentle-stream: cannot open the audio output: Error querying device -1\n"


def test_the_tui_attaches_to_the_music_already_playing(runtime, monkeypatch):
    from gentle_stream import client
    from gentle_stream.app import StreamApp

    running = client.ensure()
    seen = []
    monkeypatch.setattr(StreamApp, "run", lambda self: seen.append((self.player.pid, self.initial_mood)))
    assert main(["--mood", "foggy harbour"]) == 0
    assert seen == [(running.pid, "foggy harbour")]   # no second player, the mood goes to the running one


def test_ctl_rejects_an_unknown_action(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["ctl", "louder"])
    assert exit_info.value.code == 2


def test_ctl_tempo_without_a_player_says_nothing_is_playing(runtime, capsys):
    assert main(["ctl", "tempo", "110"]) == 1
    out, err = capsys.readouterr()
    assert out == "" and err == "gentle-stream: nothing is playing\n"


def test_ctl_glide_without_a_player_says_nothing_is_playing(runtime, capsys):
    assert main(["ctl", "glide", "energy=0.9", "--over", "30"]) == 1
    assert capsys.readouterr() == ("", "gentle-stream: nothing is playing\n")


@pytest.mark.parametrize("argv", [
    ["ctl", "glide"],
    ["ctl", "glide", "energy"],
    ["ctl", "glide", "energy=loud"],
    ["ctl", "glide", "genre=jazz"],
    ["ctl", "glide", "energy=0.9", "energy=0.2"],
    ["ctl", "tempo"],
    ["ctl", "tempo", "fast"],
    ["ctl", "tempo", "110", "120"],
    ["ctl", "play", "5"],
], ids=["no-fields", "no-value", "not-a-number", "discrete-field", "repeated-field", "tempo-no-bpm",
        "tempo-not-a-number", "tempo-two-values", "play-with-value"])
def test_ctl_rejects_malformed_arguments_before_contacting_the_player(argv, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2 and capsys.readouterr().err.startswith("usage: ")


def test_ctl_glide_tells_how_to_restart_an_older_player(monkeypatch, capsys):
    from gentle_stream import client

    class OldPlayer:
        def glide(self, fields, seconds):
            raise client.PlayerError("bad request: unknown command 'glide'")

        def detach(self):
            pass

    monkeypatch.setattr(client, "connect", lambda: OldPlayer())
    assert main(["ctl", "glide", "energy=0.9"]) == 1
    assert capsys.readouterr().err == ("gentle-stream: the running player is older than this gentle-stream; "
                                       "run `gentle-stream ctl stop` and start again\n")


def test_ctl_glide_reaches_a_running_player(runtime, capsys):
    from gentle_stream import client

    client.ensure()
    assert main(["ctl", "glide", "energy=0.9", "brightness=0.8", "--over", "30"]) == 0
    assert capsys.readouterr() == ("", "")
    assert main(["ctl", "tempo", "100"]) == 0
    assert capsys.readouterr() == ("", "")


def test_ctl_status_includes_bpm_and_target_bpm(runtime, capsys):
    import json

    from gentle_stream import client

    client.ensure()
    assert main(["ctl", "status"]) == 0
    state = json.loads(capsys.readouterr().out)
    assert state["bpm"] == pytest.approx(72.0) and state["target_bpm"] is None
    assert main(["ctl", "tempo", "110", "--over", "30"]) == 0
    capsys.readouterr()
    assert main(["ctl", "status"]) == 0
    state = json.loads(capsys.readouterr().out)
    assert state["target_bpm"] == pytest.approx(110.0)


def test_help_lists_the_setup_samples_command(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "setup-samples" in capsys.readouterr().out


def test_help_lists_the_render_command(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "render" in out and "OUT.wav" in out


def test_setup_samples_installs_once_and_reports_it(tmp_path, monkeypatch, capsys):
    from gentle_stream import samples
    from tests.test_samples import make_deb

    url, sha = make_deb(tmp_path / "pkg.deb")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(samples, "DEB_URL", url)
    monkeypatch.setattr(samples, "DEB_SHA256", sha)
    assert main(["setup-samples"]) == 0
    out = capsys.readouterr().out
    assert "installed" in out and "FluidR3_GM.sf2" in out and "MIT" in out
    assert main(["setup-samples"]) == 0
    assert "already installed" in capsys.readouterr().out


def test_setup_samples_reports_a_checksum_mismatch(tmp_path, monkeypatch, capsys):
    from gentle_stream import samples
    from tests.test_samples import make_deb

    url, _ = make_deb(tmp_path / "pkg.deb")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(samples, "DEB_URL", url)
    monkeypatch.setattr(samples, "DEB_SHA256", "0" * 64)
    assert main(["setup-samples"]) == 1
    assert "checksum" in capsys.readouterr().err.lower()
