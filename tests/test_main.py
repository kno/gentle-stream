import pytest

from gentle_stream import main
from tests.test_daemon import runtime  # noqa: F401  (fixture: private runtime dir, fake audio, cleanup)


def test_pm007_validate_show_file(tmp_path, capsys):
    source = tmp_path / "sunrise.json"
    source.write_text('{"version":1,"stages":[{"seconds":10,"to":{"bpm":999}}]}')
    assert main(["journey", "validate", str(source)]) == 0
    out, err = capsys.readouterr()
    assert '"name": "sunrise"' in out and "warning: stage 1" in err
    assert main(["journey", "show", str(source)]) == 0
    out, err = capsys.readouterr()
    assert '"bpm": 140.0' in out and err == ""


def test_pm007_show_builtin_is_canonical_json_only(capsys):
    assert main(["journey", "show", "ambient-to-synthwave"]) == 0
    out, err = capsys.readouterr()
    import json
    data = json.loads(out)
    assert data["version"] == 1 and data["name"] == "ambient-to-synthwave" and err == ""


def test_pm007_validate_is_parseable_and_warnings_are_stderr(tmp_path, capsys):
    source = tmp_path / "warn.json"
    source.write_text('{"version":1,"stages":[{"seconds":10,"to":{"bpm":999}}]}')
    assert main(["journey", "validate", str(source)]) == 0
    out, err = capsys.readouterr()
    import json
    data = json.loads(out)
    assert data["stages"][0]["to"]["bpm"] == 140.0
    assert out.count("warning") == 0 and err.startswith("warning: ") and err.endswith("\n")


def test_pm007_missing_or_invalid_json_file_is_one_error_line(tmp_path, capsys):
    missing = tmp_path / "missing.json"
    assert main(["journey", "show", str(missing)]) == 1
    out, err = capsys.readouterr()
    assert out == "" and err == f"gentle-stream: cannot read {missing}: file does not exist\n"
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not json")
    assert main(["journey", "validate", str(invalid)]) == 1
    out, err = capsys.readouterr()
    assert out == "" and err.startswith("gentle-stream: ") and err.count("\n") == 1


def test_pm007_invalid_file_is_one_error_line(tmp_path, capsys):
    source = tmp_path / "bad.json"
    source.write_text('{"version":2,"stages":[]}')
    assert main(["journey", "validate", str(source)]) == 1
    out, err = capsys.readouterr()
    assert out == "" and err.count("\n") == 1 and err.startswith("gentle-stream: ")


def test_pm007_play_file_sends_normalized_journey_to_fake_daemon(tmp_path, runtime, capsys):  # noqa: F811
    import json
    from gentle_stream import client
    from tests.test_daemon import wait_for

    source = tmp_path / "sunrise.json"
    source.write_text('{"version":1,"stages":[{"seconds":10,"to":{"bpm":999}}]}')
    client.ensure()
    assert main(["journey", "play", str(source)]) == 0
    assert capsys.readouterr() == ("", "")

    seen = {}
    def journey_started():
        main(["ctl", "status"])
        out, err = capsys.readouterr()
        assert err == ""
        seen.update(json.loads(out))
        journey = seen.get("journey")
        return journey is not None and journey["name"] == "sunrise"

    wait_for(journey_started)
    assert seen["journey"]["target_bpm"] == 140.0
    assert main(["journey", "stop"]) == 0
    assert capsys.readouterr() == ("", "")


def test_pm007_builtin_cli_outputs_and_errors(runtime, capsys):  # noqa: F811
    from gentle_stream import client
    client.ensure()
    assert main(["journey", "list"]) == 0
    listed, err = capsys.readouterr()
    assert err == "" and "warm-up" in listed and "ambient-to-synthwave" in listed
    assert main(["journey", "play", "nope"]) == 1
    out, err = capsys.readouterr()
    assert out == "" and err.startswith('gentle-stream: no journey called "nope"') and err.endswith("\n")
    assert main(["journey", "play", "warm-up"]) == 0
    assert capsys.readouterr() == ("", "")
    assert main(["journey", "stop"]) == 0
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("action", ["restart", "skip"])
def test_pm008_controls_without_a_journey_exit_1(runtime, capsys, action):  # noqa: F811
    from gentle_stream import client

    client.ensure()
    assert main(["journey", action]) == 1
    assert capsys.readouterr() == ("", "gentle-stream: no journey is running\n")


@pytest.mark.parametrize("action", ["restart", "skip"])
def test_pm008_controls_when_nothing_plays_exit_1(runtime, capsys, action):  # noqa: F811
    assert main(["journey", action]) == 1
    assert capsys.readouterr() == ("", "gentle-stream: nothing is playing\n")


def test_pm008_skip_then_restart_move_the_audible_stage(runtime, capsys):  # noqa: F811
    import json

    from gentle_stream import client
    from tests.test_daemon import wait_for

    def stage():
        main(["ctl", "status"])
        out, _ = capsys.readouterr()
        journey = json.loads(out)["journey"]
        return journey and journey["stage"]

    client.ensure()
    assert main(["journey", "play", "warm-up"]) == 0
    capsys.readouterr()
    wait_for(lambda: stage() == 1)
    assert main(["journey", "skip"]) == 0
    assert capsys.readouterr() == ("", "")
    wait_for(lambda: stage() == 2)
    assert main(["journey", "restart"]) == 0
    assert capsys.readouterr() == ("", "")
    wait_for(lambda: stage() == 1)
    assert main(["journey", "stop"]) == 0


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


# ------------------------------------------------------------ journeys
def test_journey_list_prints_the_built_ins_one_per_line_with_a_description(capsys):
    from gentle_stream.journey import BUILTIN

    assert main(["journey", "list"]) == 0
    out, err = capsys.readouterr()
    lines = out.splitlines()
    assert err == "" and len(lines) == len(BUILTIN)
    for line, journey in zip(lines, BUILTIN.values(), strict=True):
        assert line.startswith(journey.name + " ") and line.endswith(journey.description)


def test_journey_play_an_unknown_name_lists_the_built_ins_and_exits_1(monkeypatch, capsys):
    from gentle_stream import client
    from gentle_stream.journey import BUILTIN

    monkeypatch.setattr(client, "connect", lambda: pytest.fail("checked before contacting the player"))
    assert main(["journey", "play", "unknown"]) == 1
    assert capsys.readouterr() == ("", (f'gentle-stream: no journey called "unknown" (choose from '
                                        f'{", ".join(BUILTIN)})\n'))


@pytest.mark.parametrize("argv", [["journey", "play", "warm-up"], ["journey", "stop"]], ids=["play", "stop"])
def test_journey_without_a_player_says_nothing_is_playing(runtime, capsys, argv):
    assert main(argv) == 1
    assert capsys.readouterr() == ("", "gentle-stream: nothing is playing\n")


@pytest.mark.parametrize("argv", [["journey"], ["journey", "play"], ["journey", "jump"], ["journey", "stop", "x"],
                                  ["journey", "list", "x"], ["journey", "restart", "x"], ["journey", "skip", "x"]],
                         ids=["no-action", "play-no-name", "unknown-action", "stop-with-name", "list-with-name",
                              "restart-with-name", "skip-with-name"])
def test_journey_rejects_malformed_arguments(argv, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2 and capsys.readouterr().err.startswith("usage: ")


@pytest.mark.parametrize("argv, method", [(["journey", "play", "warm-up"], "journey_start"),
                                          (["journey", "stop"], "journey_stop"),
                                          (["journey", "restart"], "journey_restart"),
                                          (["journey", "skip"], "journey_skip")],
                         ids=["play", "stop", "restart", "skip"])
def test_journey_tells_how_to_restart_an_older_player(monkeypatch, capsys, argv, method):
    from gentle_stream import client

    class OldPlayer:
        def detach(self):
            pass

    def refuse(*args):
        raise client.PlayerError(f"bad request: unknown command {method!r}")

    setattr(OldPlayer, method, refuse)
    monkeypatch.setattr(client, "connect", lambda: OldPlayer())
    assert main(argv) == 1
    assert capsys.readouterr() == ("", ("gentle-stream: the running player is older than this gentle-stream; "
                                        "run `gentle-stream ctl stop` and start again\n"))


def test_journey_play_and_stop_reach_a_running_player(runtime, capsys):
    import json

    from gentle_stream import client
    from tests.test_daemon import wait_for

    client.ensure()
    assert main(["journey", "play", "warm-up"]) == 0
    assert capsys.readouterr() == ("", "")

    def bpm():
        main(["ctl", "status"])
        return json.loads(capsys.readouterr().out)["bpm"]

    wait_for(lambda: bpm() < 72.0)                 # warm-up's first stage settles towards 60 bpm
    assert main(["journey", "stop"]) == 0
    assert capsys.readouterr() == ("", "")


def test_help_lists_the_journey_command(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "journey play NAME" in out and "journey list" in out and "journey stop" in out and "--journey" in out


def test_ctl_status_reports_the_running_journey(runtime, capsys):
    import json

    from gentle_stream import client
    from tests.test_daemon import wait_for

    client.ensure()

    def status():
        main(["ctl", "status"])
        return json.loads(capsys.readouterr().out)

    assert status()["journey"] is None
    assert main(["journey", "play", "warm-up"]) == 0
    wait_for(lambda: status()["journey"] is not None)
    state = status()
    assert list(state) == ["running", "playing", "name", "genre", "mood", "bpm", "target_bpm", "journey"]
    journey = state["journey"]
    assert (journey["name"], journey["title"], journey["stage"], journey["stages"], journey["stage_name"]) == (
        "warm-up", "Warm-up", 1, 4, "Settle")
    assert journey["target_bpm"] == 60.0 and 0 < journey["seconds_left"] <= 600


def test_ctl_glide_and_tempo_refuse_the_fields_a_journey_drives(runtime, capsys):
    from gentle_stream import client

    client.ensure()
    assert main(["journey", "play", "warm-up"]) == 0
    capsys.readouterr()
    assert main(["ctl", "tempo", "110"]) == 1
    assert capsys.readouterr() == ("", ('gentle-stream: bpm is driven by the journey "warm-up"; stop it first '
                                        "(gentle-stream journey stop)\n"))
    assert main(["ctl", "glide", "energy=0.9", "space=0.8"]) == 1
    assert capsys.readouterr() == ("", ('gentle-stream: energy is driven by the journey "warm-up"; stop it first '
                                        "(gentle-stream journey stop)\n"))
    assert main(["ctl", "glide", "space=0.8"]) == 0
    assert main(["journey", "stop"]) == 0
    assert main(["ctl", "tempo", "110"]) == 0
    assert capsys.readouterr() == ("", "")
