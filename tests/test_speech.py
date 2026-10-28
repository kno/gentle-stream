"""PM-031: spoken phrases over the music, with fake text-to-speech executables (never the real `say`)."""
import json
import os
import sys

import numpy as np
import pytest

from gentle_stream import daemon, main, speech
from gentle_stream.engine import Engine
from gentle_stream.speech import DUCK_DB, MAX_TEXT, RAMP, SpeechError
from gentle_stream.style import Style
from gentle_stream.synth import SR

FAKE = """#!{python} -I
import json, sys, wave
import numpy as np
args = sys.argv[1:]
text = sys.stdin.read()
with open({log!r}, "a") as f:
    f.write(json.dumps({{"argv": [sys.argv[0].rsplit("/", 1)[-1]] + args, "stdin": text}}) + "\\n")
if "FAIL" in text:
    sys.stderr.write("synthesis failed: no voice\\n")
    sys.exit(3)
out = args[args.index("-o" if "-o" in args else "-w") + 1]
sr = 22050
n = int(sr * 0.05 * max(1, len(text)))
x = 0.4 * np.sin(2 * np.pi * 300 * np.arange(n) / sr)
x[0] = 0.9                                         # a marker: the clip's first sample stands out
with wave.open(out, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((x * 32767).astype("<i2").tobytes())
"""


@pytest.fixture
def tts(tmp_path, monkeypatch):
    """A bin dir on PATH holding fake `say` and `espeak-ng`; returns a function that installs one of them and the
    path of the log of every call (argv and stdin)."""
    bin_dir, log = tmp_path / "bin", tmp_path / "tts.log"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    speech.clear_cache()

    def install(*names):
        for name in names:
            path = bin_dir / name
            path.write_text(FAKE.format(python=sys.executable, log=str(log)))
            path.chmod(0o755)
        return log

    yield install
    speech.clear_cache()


def calls(log):
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


# ------------------------------------------------------------ the backend
def test_say_is_used_on_macos_with_the_text_on_stdin(tts):
    log = tts("say", "espeak-ng")                      # say wins when both exist
    clip = speech.render("Keep going")
    (call,) = calls(log)
    assert call["argv"][0] == "say" and call["argv"][1] == "-o"
    assert call["argv"][3:] == ["--data-format=LEI16@22050"]
    assert call["stdin"] == "Keep going" and "Keep going" not in call["argv"]
    assert clip.ndim == 1 and len(clip) == pytest.approx(0.05 * 10 * SR, rel=0.01)


def test_espeak_ng_is_used_when_say_is_missing(tts):
    log = tts("espeak-ng")
    speech.render("--help me")                          # an option-looking text stays text
    (call,) = calls(log)
    assert call["argv"][0] == "espeak-ng" and call["argv"][1] == "-w" and call["argv"][3:] == ["--stdin"]
    assert call["stdin"] == "--help me"


def test_without_a_backend_the_error_says_so(tts):
    with pytest.raises(SpeechError, match="^no text-to-speech backend found"):
        speech.render("Keep going")


def test_a_failing_backend_reports_its_error(tts):
    tts("say")
    with pytest.raises(SpeechError, match="text-to-speech failed: synthesis failed: no voice"):
        speech.render("FAIL now")


def test_clips_are_cached_by_text(tts):
    log = tts("say")
    a = speech.render("Keep going")
    b = speech.render("Keep going")
    speech.render("Almost there")
    assert a is b and len(calls(log)) == 2


@pytest.mark.parametrize("text", ["", "   ", "x" * (MAX_TEXT + 1)])
def test_empty_or_long_text_is_refused_before_the_backend_runs(tts, text):
    log = tts("say")
    with pytest.raises(SpeechError, match="between 1 and"):
        speech.render(text)
    assert calls(log) == []


def test_clips_are_level_normalised_and_never_loud(tts):
    tts("say")
    clip = speech.render("Keep going")                   # a quiet tone: normalised up to the target RMS
    assert np.sqrt(np.mean(clip ** 2)) == pytest.approx(speech.SPEECH_RMS, rel=0.02)
    speech.clear_cache()
    loud = speech.normalise(np.r_[np.ones(10), np.zeros(SR)])   # one spike: the peak limit wins over the RMS
    assert np.abs(loud).max() == pytest.approx(speech.SPEECH_PEAK)


# ------------------------------------------------------------ in the music
def bar_samples(e):
    return round(e.bar_seconds * e.sr)


def render(clip, queue_after, bars=10):
    """(with, without): the same engine rendered with `clip` queued after `queue_after` bars, and without it."""
    a, b = Engine(Style(), seed=4, samples=False), Engine(Style(), seed=4, samples=False)
    out_a, out_b = [], []
    for i in range(bars):
        if i == queue_after:
            a.queue_speech(clip)
        out_a.append(a.render_bar())
        out_b.append(b.render_bar())
    return np.concatenate(out_a).astype(float), np.concatenate(out_b).astype(float), bar_samples(a)


@pytest.mark.parametrize("queue_after, boundary_bar", [(1, 4), (4, 4), (5, 8)])
def test_the_clip_starts_exactly_on_a_phrase_boundary_sample(queue_after, boundary_bar):
    clip = np.zeros(SR)
    clip[0] = 0.3
    with_clip, without, n = render(clip, queue_after)
    diff = with_clip - without
    start = boundary_bar * n
    assert np.all(diff[:start] == 0)                          # nothing changes before the boundary
    assert diff[start, 0] == pytest.approx(0.3, abs=1e-6) and diff[start, 1] == pytest.approx(0.3, abs=1e-6)


def test_the_music_is_ducked_3_db_under_the_clip_with_click_free_ramps():
    silent = np.zeros(int(2.0 * SR))                          # silence: the difference is the duck alone
    with_clip, without, n = render(silent, 1)
    start, ramp = 4 * n, int(RAMP * SR)
    gain = np.ones(len(without))
    nz = np.abs(without[:, 0]) > 1e-4
    gain[nz] = with_clip[nz, 0] / without[nz, 0]
    held = gain[start + ramp + 10:start + len(silent) - 10][nz[start + ramp + 10:start + len(silent) - 10]]
    assert np.allclose(held, 10 ** (-DUCK_DB / 20), atol=1e-4)
    env = speech.duck_envelope(len(silent))
    assert env[0] == 1.0 and env[-1] == pytest.approx(1.0, abs=(1 - 10 ** (-DUCK_DB / 20)) / ramp + 1e-9)
    assert np.abs(np.diff(env)).max() <= (1 - 10 ** (-DUCK_DB / 20)) / ramp * 1.001   # linear, ~50 ms each way
    after = start + len(env) + 10
    assert np.allclose(with_clip[after:after + n], without[after:after + n], atol=1e-6)   # back to full level


def test_two_phrases_play_one_after_the_other_on_boundaries():
    a = Engine(Style(), seed=4, samples=False)
    n = bar_samples(a)
    first, second = np.zeros(n), np.zeros(n)
    first[0], second[0] = 0.3, 0.2
    a.queue_speech(first)
    a.queue_speech(second)
    b = Engine(Style(), seed=4, samples=False)
    diff = np.concatenate([a.render_bar() for _ in range(9)]).astype(float) - \
        np.concatenate([b.render_bar() for _ in range(9)]).astype(float)
    assert diff[0, 0] == pytest.approx(0.3, abs=1e-6)        # bar 0 is a boundary
    assert diff[4 * n, 0] == pytest.approx(0.2, abs=1e-6)    # the second waits for the next one


def test_render_bar_never_runs_text_to_speech(monkeypatch):
    monkeypatch.setattr(speech, "render", lambda *a, **k: pytest.fail("text-to-speech ran on the render thread"))
    e = Engine(Style(), seed=4, samples=False)
    e.queue_speech(np.full(SR, 0.1))
    for _ in range(6):
        e.render_bar()


# ------------------------------------------------------------ the player and the command
def fake_player():
    from tests.test_daemon import fake_player as make
    return make()


def test_the_player_speaks_on_request(tts):
    tts("say")
    player = fake_player()
    answer = daemon.handle(player, {"cmd": "say", "text": "Keep going"})
    assert answer["ok"] is True
    assert len(player.engine._speech_queue) == 1


def test_a_failing_backend_leaves_the_music_untouched_and_reports_the_error(tts):
    tts("say")
    player = fake_player()
    answer = daemon.handle(player, {"cmd": "say", "text": "FAIL now"})
    assert answer == {"ok": False, "error": "text-to-speech failed: synthesis failed: no voice"}
    assert player.engine._speech_queue == []


@pytest.mark.parametrize("request_, error", [({"cmd": "say"}, "bad request: 'text'"),
                                             ({"cmd": "say", "text": 3}, "bad request: text must be a string")])
def test_malformed_say_requests_are_refused(request_, error):
    assert daemon.handle(fake_player(), request_) == {"ok": False, "error": error}


class FakeClient:
    def __init__(self, error=None):
        self.said, self.error, self.detached = [], error, False

    def say(self, text, voice=None, rate=None, effect="dry"):
        from gentle_stream.client import PlayerError
        if self.error:
            raise PlayerError(self.error)
        self.said.append((text, voice, rate, effect))
        return []

    def detach(self):
        self.detached = True


def test_ctl_say_sends_the_whole_text(monkeypatch, capsys):
    from gentle_stream import client
    fake = FakeClient()
    monkeypatch.setattr(client, "connect", lambda: fake)
    assert main(["ctl", "say", "Keep", "going"]) == 0
    assert fake.said == [("Keep going", None, None, "dry")] and fake.detached   # no options: the defaults
    assert capsys.readouterr() == ("", "")


def test_ctl_say_reports_the_players_error(monkeypatch, capsys):
    from gentle_stream import client
    monkeypatch.setattr(client, "connect", lambda: FakeClient("no text-to-speech backend found (macOS has say; "
                                                              "on Linux install espeak-ng)"))
    assert main(["ctl", "say", "Keep going"]) == 1
    assert capsys.readouterr() == ("", ("gentle-stream: no text-to-speech backend found (macOS has say; on Linux "
                                        "install espeak-ng)\n"))


def test_ctl_say_needs_text(capsys):
    with pytest.raises(SystemExit) as e:
        main(["ctl", "say"])
    assert e.value.code == 2 and "say requires TEXT" in capsys.readouterr().err


def test_ctl_say_without_a_player(monkeypatch, capsys):
    from gentle_stream import client

    def none():
        raise client.NoPlayer("nothing is playing")

    monkeypatch.setattr(client, "connect", none)
    assert main(["ctl", "say", "hi"]) == 1
    assert capsys.readouterr() == ("", "gentle-stream: nothing is playing\n")


def test_the_temporary_wav_is_removed(tts, tmp_path, monkeypatch):
    tts("say")
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", None)
    speech.render("Keep going")
    assert os.listdir(tmp_path / "tmp") == []
