"""`ctl say --sing` and the say dialog's Sing switch (S2): the phrase sung on the next bar's planned notes, as a lead
vocal, through the player, the daemon, the client and the TUI. A fake `say` speaks two syllables: a noise burst
(the consonant) then a 120 Hz harmonic vowel, each."""
import sys

import numpy as np
import pytest
from textual.widgets import Checkbox, Input

from gentle_stream import daemon, main, sing, speech
from gentle_stream.app import SayModal
from tests.test_app import FakeShell, make_app
from tests.test_sing import f0_at, voiced_spans

FAKE_VOICE = """#!{python} -I
import sys, wave
import numpy as np
args = sys.argv[1:]
sys.stdin.read()
out = args[args.index("-o") + 1]
sr = 22050
rng = np.random.default_rng(1)
t = np.arange(int(0.18 * sr)) / sr
vowel = sum(0.3 / k * np.sin(2 * np.pi * 120 * k * t) for k in range(1, 12)) * np.hanning(len(t)) ** 0.3
parts = [np.zeros(int(0.1 * sr))]
for _ in range(2):
    parts += [0.05 * rng.standard_normal(int(0.05 * sr)), vowel, np.zeros(int(0.08 * sr))]
x = np.concatenate(parts)
with wave.open(out, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((x * 32767).astype("<i2").tobytes())
"""


@pytest.fixture
def tts(tmp_path, monkeypatch):
    bin_dir, log = tmp_path / "bin", tmp_path / "tts.log"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    path = bin_dir / "say"
    path.write_text(FAKE_VOICE.format(python=sys.executable))
    path.chmod(0o755)
    speech.clear_cache()
    yield log
    speech.clear_cache()


def fake_player():
    from tests.test_daemon import fake_player as make
    return make()


def queued(player):
    return list(player.engine._speech_queue)


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


# ------------------------------------------------------------ the player
def test_a_sung_phrase_is_queued_for_the_next_bar_on_its_planned_notes(tts):
    player = fake_player()
    bar = player.engine.bar
    assert player.say("Keep going", sing=True) == []
    [clip] = queued(player)
    assert clip.at_bar == bar + 1 and clip.duck_db == sing.SING_DUCK_DB
    notes = sing.transpose(player.engine.melody_ahead(bar + 1, sing.BARS_AHEAD))
    sr = player.engine.sr
    spans = voiced_spans(clip.clip, sr)
    assert len(spans) == 2                                                 # the fake's two syllables
    for start, end in spans:
        mid = (start + end) / 2
        sounding = [n for n in notes if n.start <= mid < n.start + n.length]
        assert sounding and f0_at(clip.clip, mid, sr) == pytest.approx(hz(sounding[0].midi), rel=0.03)
        assert any(abs(start - n.start) < 0.04 for n in notes)            # each one starts on a note
    assert np.abs(clip.clip[:max(0, int((notes[0].start - 0.06) * sr))]).max(initial=0) < 1e-3


def test_a_spoken_phrase_is_unchanged(tts):
    player = fake_player()
    player.say("Keep going")
    [clip] = queued(player)
    assert clip.at_bar is None and clip.every == 1 and clip.duck_db == speech.DUCK_DB


def test_singing_without_pyworld_says_how_to_install_it_and_queues_nothing(tts, monkeypatch):
    monkeypatch.setattr(sing, "available", lambda: False)
    player = fake_player()
    with pytest.raises(speech.SpeechError, match="^singing needs pyworld"):
        player.say("Keep going", sing=True)
    assert queued(player) == []


# ------------------------------------------------------------ the daemon and the client
def test_the_daemon_sings_on_request(tts):
    player = fake_player()
    answer = daemon.handle(player, {"cmd": "say", "text": "Keep going", "sing": True})
    assert answer["ok"] is True
    assert queued(player)[0].at_bar is not None


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_a_malformed_sing_is_refused(tts, value):
    player = fake_player()
    answer = daemon.handle(player, {"cmd": "say", "text": "Hi", "sing": value})
    assert answer == {"ok": False, "error": "bad request: sing must be true or false"}
    assert queued(player) == []


class FakeClient:
    def __init__(self):
        self.calls = []

    def say(self, text, **options):
        self.calls.append((text, options))
        return []

    def detach(self):
        pass


def test_ctl_say_sing_asks_the_player_to_sing(monkeypatch, capsys):
    from gentle_stream import client

    fake = FakeClient()
    monkeypatch.setattr(client, "connect", lambda: fake)
    assert main(["ctl", "say", "Keep", "going", "--sing"]) == 0
    assert fake.calls == [("Keep going", {"voice": None, "rate": None, "effect": "dry", "sing": True})]
    assert capsys.readouterr() == ("", "")


def test_ctl_say_without_sing_sends_no_sing(monkeypatch):
    from gentle_stream import client

    fake = FakeClient()
    monkeypatch.setattr(client, "connect", lambda: fake)
    assert main(["ctl", "say", "Hi"]) == 0
    assert fake.calls == [("Hi", {"voice": None, "rate": None, "effect": "dry"})]


def test_sing_is_only_for_say(capsys):
    with pytest.raises(SystemExit) as e:
        main(["ctl", "glide", "energy=0.5", "--sing"])
    assert e.value.code == 2
    assert "--voice, --rate, --effect and --sing are only for say" in capsys.readouterr().err


def test_the_client_sends_sing_only_when_asked(monkeypatch):
    from gentle_stream.client import PlayerClient

    sent = []
    client = PlayerClient.__new__(PlayerClient)
    monkeypatch.setattr(client, "_round_trip", lambda cmd, **args: sent.append((cmd, args)) or {"ok": True},
                        raising=False)
    client.say("Hi")
    client.say("Hi", sing=True)
    assert sent == [("say", {"text": "Hi", "effect": "dry"}), ("say", {"text": "Hi", "effect": "dry", "sing": True})]


def test_help_names_sing(capsys):
    with pytest.raises(SystemExit):
        main(["ctl", "--help"])
    assert "--sing" in capsys.readouterr().out


# ------------------------------------------------------------ the TUI
@pytest.mark.asyncio
async def test_the_say_dialogs_sing_switch_sings_the_phrase(tts):
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.press("t")
        await pilot.pause(0.1)
        screen = app.screen
        assert isinstance(screen, SayModal)
        await app.workers.wait_for_complete()
        screen.query_one("#say-text", Input).value = "Keep going"
        screen.query_one("#say-sing", Checkbox).value = True
        await pilot.click("#say")
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)
        assert not isinstance(app.screen, SayModal)
        [clip] = queued(player)
        assert clip.at_bar is not None and clip.duck_db == sing.SING_DUCK_DB


@pytest.mark.asyncio
async def test_the_sing_switch_starts_off_and_fits_in_80_by_24(tts):
    app, _ = make_app(FakeShell())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("t")
        await pilot.pause(0.1)
        box = app.screen.query_one("#say-sing", Checkbox)
        assert box.value is False
        assert box.region.width > 0 and box.region.right <= 80 and box.region.bottom <= 24


def test_a_broadcast_never_reuses_a_voice_analysed_before_it(tts):
    sing.voice_for("Keep going", None, None)                       # analysed with `say`, a personal-use voice
    speech.use_only(speech.BROADCAST_SAFE)
    try:
        with pytest.raises(speech.SpeechError, match="^while broadcasting, phrases are spoken with Piper"):
            sing.voice_for("Keep going", None, None)
    finally:
        speech.use_only(None)
