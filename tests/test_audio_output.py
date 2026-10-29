"""S8/S9: choose the audio output (`ctl output`, the TUI), live and remembered; a one-channel output gets the two
channels mixed; and when no output opens the player still starts, silent here, so a broadcast goes on."""
import time

import numpy as np
import pytest

from gentle_stream import main, outputs
from gentle_stream.engine import Engine
from gentle_stream.outputs import OutputError
from gentle_stream.player import Player, SilentStream
from gentle_stream.style import Style
from tests.test_player import FakeStream

DEVICES = [{"name": "DELL U3415W", "max_output_channels": 2, "default_samplerate": 48000.0},
           {"name": "MacBook Microphone", "max_output_channels": 0, "default_samplerate": 48000.0},
           {"name": "WH-1000XM3", "max_output_channels": 1, "default_samplerate": 16000.0},
           {"name": "Altavoces del MacBook Pro", "max_output_channels": 2, "default_samplerate": 48000.0}]


@pytest.fixture(autouse=True)
def devices(monkeypatch):
    """Three outputs and a microphone; the system default is the headphones (index 2)."""
    monkeypatch.setattr(outputs, "_query", lambda: (DEVICES, 2))


class Streams:
    """A stream factory that records every stream opened, and can refuse some devices."""

    def __init__(self, refuse=()):
        self.opened, self.refuse = [], set(refuse)

    def __call__(self, **kw):
        if kw.get("device") in self.refuse or ("default" in self.refuse and kw.get("device") is None):
            raise RuntimeError(f"Error opening OutputStream: Invalid number of channels [device {kw.get('device')}]")
        stream = FakeStream(**kw)
        self.opened.append(stream)
        return stream


def make_player(streams) -> Player:
    player = Player(Engine(Style(), seed=1, samples=False), stream_factory=streams, prebuffer=0.3)
    player.start()
    return player


# ------------------------------------------------------------ the list and the remembered choice
def test_the_outputs_are_the_devices_that_play_with_the_system_default_marked():
    assert [(o.name, o.channels, o.default) for o in outputs.available()] == [
        ("DELL U3415W", 2, False), ("WH-1000XM3", 1, True), ("Altavoces del MacBook Pro", 2, False)]
    found = outputs.find("altavoces del macbook pro")
    assert found is not None and found.name == "Altavoces del MacBook Pro"
    assert outputs.find("Nowhere") is None


def test_the_choice_is_remembered_in_the_config_dir():
    assert outputs.saved() is None
    outputs.save("DELL U3415W")
    assert outputs.saved() == "DELL U3415W"
    outputs.save(None)
    assert outputs.saved() is None


# ------------------------------------------------------------ the player
def test_the_player_opens_the_remembered_output():
    outputs.save("DELL U3415W")
    streams = Streams()
    player = make_player(streams)
    try:
        assert streams.opened[0].kw["device"] == 0 and streams.opened[0].kw["channels"] == 2
        assert player.output == {"name": "DELL U3415W", "channels": 2, "silent": False, "error": None}
    finally:
        player.close()


def test_a_one_channel_output_gets_both_channels_mixed():
    """The headphones in hands-free mode: one channel. The broadcast and the recording stay stereo."""
    streams = Streams()
    player = make_player(streams)
    try:
        assert streams.opened[0].kw["channels"] == 1 and player.output["channels"] == 1
        block = streams.opened[0].pull(512)
        assert block.shape == (512, 1) and np.isfinite(block).all() and np.abs(block).max() > 0
    finally:
        player.close()


def test_switching_is_live_remembered_and_closes_the_old_stream():
    streams = Streams()
    player = make_player(streams)
    try:
        old = streams.opened[0]
        assert player.set_output("Altavoces del MacBook Pro")["name"] == "Altavoces del MacBook Pro"
        assert streams.opened[-1].kw["device"] == 3 and streams.opened[-1].active and not old.active
        assert outputs.saved() == "Altavoces del MacBook Pro"
        assert np.abs(streams.opened[-1].pull(512)).max() > 0       # it plays on the new one
        assert player.set_output(None)["name"] == "WH-1000XM3"      # back to the system default
        assert outputs.saved() is None
    finally:
        player.close()


def test_an_unknown_output_is_refused_and_nothing_changes():
    streams = Streams()
    player = make_player(streams)
    try:
        with pytest.raises(OutputError, match=r'no audio output called "Nowhere" \(see gentle-stream ctl output\)'):
            player.set_output("Nowhere")
        assert len(streams.opened) == 1 and streams.opened[0].active
    finally:
        player.close()


def test_a_chosen_output_that_fails_falls_back_to_the_system_default():
    outputs.save("DELL U3415W")
    streams = Streams(refuse={0})
    player = make_player(streams)
    try:
        out = player.output
        assert out["name"] == "WH-1000XM3" and not out["silent"]
        assert "DELL U3415W" in out["error"] and "Invalid number of channels" in out["error"]
    finally:
        player.close()


def test_with_no_output_that_opens_the_player_still_starts_silent_and_keeps_time():
    """S9: nothing opens; the music goes on by the clock (a broadcast or a recording keeps working)."""
    streams = Streams(refuse={0, 2, 3, "default"})
    player = make_player(streams)
    try:
        out = player.output
        assert out["silent"] and out["name"] is None and "Invalid number of channels" in out["error"]
        assert isinstance(player._stream, SilentStream)
        start = player.position
        time.sleep(0.5)
        advanced = (player.position - start) / player.engine.sr
        assert 0.35 < advanced < 0.65                               # real time, not faster
        assert player.level > 0                                     # the music is there
    finally:
        player.close()


# ------------------------------------------------------------ the background player and ctl
def test_the_daemon_lists_switches_and_reports_the_output():
    from gentle_stream.daemon import handle, state
    from tests.test_daemon import fake_player

    player = fake_player()
    player.start()
    try:
        listed = handle(player, {"cmd": "outputs"})
        assert listed["ok"] and [o["name"] for o in listed["outputs"]] == ["DELL U3415W", "WH-1000XM3",
                                                                         "Altavoces del MacBook Pro"]
        assert handle(player, {"cmd": "set_output", "name": "DELL U3415W"})["ok"]
        assert state(player)["output"]["name"] == "DELL U3415W" and list(state(player))[-1] == "output"
        refused = handle(player, {"cmd": "set_output", "name": "Nowhere"})
        assert refused == {"ok": False, "error": 'no audio output called "Nowhere" (see gentle-stream ctl output)'}
        assert handle(player, {"cmd": "set_output", "name": 3})["ok"] is False
    finally:
        player.close()


class FakeClient:
    def __init__(self):
        self.output = {"name": "WH-1000XM3", "channels": 1, "silent": False, "error": None}
        self.calls = []

    def outputs(self):
        return [{"name": o.name, "channels": o.channels, "default": o.default} for o in outputs.available()]

    def set_output(self, name):
        from gentle_stream.client import PlayerError

        self.calls.append(name)
        if name == "Nowhere":
            raise PlayerError('no audio output called "Nowhere" (see gentle-stream ctl output)')
        self.output = {"name": name or "WH-1000XM3", "channels": 2, "silent": False, "error": None}
        return self.output

    def detach(self):
        pass


def test_ctl_output_lists_marks_and_switches(monkeypatch, capsys):
    from gentle_stream import client

    fake = FakeClient()
    monkeypatch.setattr(client, "connect", lambda: fake)
    assert main(["ctl", "output"]) == 0
    assert capsys.readouterr().out == ("  DELL U3415W · 2 channels\n"
                                       "* WH-1000XM3 · 1 channel · system default\n"
                                       "  Altavoces del MacBook Pro · 2 channels\n")
    assert main(["ctl", "output", "Altavoces del MacBook Pro"]) == 0
    assert capsys.readouterr().out == "Playing on Altavoces del MacBook Pro\n"
    assert main(["ctl", "output", "default"]) == 0
    assert capsys.readouterr().out == "Playing on WH-1000XM3 (the system default)\n"
    assert fake.calls == ["Altavoces del MacBook Pro", None]
    assert main(["ctl", "output", "Nowhere"]) == 1
    assert capsys.readouterr().err == 'gentle-stream: no audio output called "Nowhere" (see gentle-stream ctl output)\n'


def test_ctl_output_without_a_player(capsys):
    assert main(["ctl", "output"]) == 1
    assert capsys.readouterr().err == "gentle-stream: nothing is playing\n"


# ------------------------------------------------------------ the TUI
@pytest.mark.asyncio
async def test_o_lists_the_outputs_and_picking_one_switches(monkeypatch):
    from textual.widgets import OptionList

    from gentle_stream.app import OutputModal
    from tests.test_app import FakeShell, make_app, text

    app, player = make_app(FakeShell())
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("o")
        await pilot.pause(0.2)
        assert isinstance(app.screen, OutputModal)
        options = app.screen.query_one("#outputs", OptionList)
        prompts = [str(options.get_option_at_index(i).prompt) for i in range(options.option_count)]
        assert prompts[0] == "System default (WH-1000XM3)" and "Altavoces del MacBook Pro · 2 channels" in prompts
        options.highlighted = prompts.index("Altavoces del MacBook Pro · 2 channels")
        await pilot.press("enter")
        await pilot.pause(0.6)
        assert not isinstance(app.screen, OutputModal)
        assert player.output["name"] == "Altavoces del MacBook Pro"
        assert "out: Altavoces del MacBook Pro" in text(app, "#state")


@pytest.mark.asyncio
async def test_without_sound_here_the_state_line_says_so():
    from tests.test_app import FakeShell, make_app, text

    app, player = make_app(FakeShell())
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause(0.2)
        player._output = {"name": None, "channels": 2, "silent": True, "error": "no output device"}
        await pilot.pause(0.6)
        assert "no sound here (o)" in text(app, "#state")


def test_the_palette_offers_the_audio_output():
    from gentle_stream.app import StreamApp

    assert "Audio output" in {title for title, _, _ in StreamApp.palette_actions()}

