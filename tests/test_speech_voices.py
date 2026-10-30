"""PM-033: the speaking voice, rate and effect of phrases (fake text-to-speech programs, never the real ones)."""
import json
import sys

import numpy as np
import pytest

from gentle_stream import daemon, main, speech
from gentle_stream.speech import EFFECTS, RATES, SpeechError
from gentle_stream.synth import SR

FAKE = """#!{python} -I
import json, sys, wave
import numpy as np
args = sys.argv[1:]
name = sys.argv[0].rsplit("/", 1)[-1]
if args == ["-v", "?"]:
    print("Samantha            en_US    # Hello! My name is Samantha.")
    print("Bad News            en_US    # The light you see at the end of the tunnel is the headlamp.")
    print("Paulina             es_MX    # Hola! Me llamo Paulina.")
    sys.exit(0)
if args == ["--voices"]:
    print("Pty Language       Age/Gender VoiceName          File                 Other Languages")
    print(" 5  en-us           --/M      English_(America)  gmw/en-US            (en 2)")
    print(" 5  es              --/M      Spanish_(Spain)    roa/es               ")
    sys.exit(0)
text = sys.stdin.read()
with open({log!r}, "a") as f:
    f.write(json.dumps({{"argv": [name] + args, "stdin": text}}) + "\\n")
out = args[args.index("-o" if "-o" in args else "-w") + 1]
sr = 22050
t = np.arange(int(sr * 0.6)) / sr
x = 0.25 * (np.sin(2 * np.pi * 150 * t) + np.sin(2 * np.pi * 1000 * t) + np.sin(2 * np.pi * 6000 * t))  # low, mid, high
with wave.open(out, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((x * 32767).astype("<i2").tobytes())
"""


@pytest.fixture
def tts(tmp_path, monkeypatch):
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


def argv(log):
    return [json.loads(line)["argv"] for line in log.read_text().splitlines()]


# ------------------------------------------------------------ options reach the command line exactly
def test_say_gets_voice_and_rate_exactly(tts):
    log = tts("say")
    speech.render("Almost there", voice="Samantha", rate=180)
    (cmd,) = argv(log)
    assert cmd[0] == "say" and cmd[1] == "-o"
    assert cmd[3:] == ["--data-format=LEI16@22050", "-v", "Samantha", "-r", "180"]


def test_espeak_ng_gets_voice_and_rate_exactly(tts):
    log = tts("espeak-ng")
    speech.render("Almost there", voice="es", rate=150)
    (cmd,) = argv(log)
    assert cmd[0] == "espeak-ng" and cmd[1] == "-w" and cmd[3:] == ["-v", "es", "-s", "150", "--stdin"]


def test_a_voice_name_with_spaces_stays_one_argument(tts):
    log = tts("say")
    speech.render("Almost there", voice="Bad News")
    assert argv(log)[0][3:] == ["--data-format=LEI16@22050", "-v", "Bad News"]


def test_without_options_the_command_line_is_unchanged(tts):
    log = tts("say")
    speech.render("Almost there")
    assert argv(log)[0][3:] == ["--data-format=LEI16@22050"]


@pytest.mark.parametrize("rate", [RATES[0] - 1, RATES[1] + 1, 0])
def test_a_rate_out_of_range_is_refused_before_the_program_runs(tts, rate):
    log = tts("say")
    with pytest.raises(SpeechError, match=f"rate must be {RATES[0]} to {RATES[1]} words per minute"):
        speech.render("Hi", rate=rate)
    assert not log.exists()


def test_clips_are_cached_per_voice_rate_and_effect(tts):
    log = tts("say")
    a = speech.render("Hi", voice="Samantha")
    assert speech.render("Hi", voice="Samantha") is a
    speech.render("Hi", voice="Paulina")
    speech.render("Hi", voice="Samantha", rate=200)
    radio = speech.render("Hi", voice="Samantha", effect="radio")   # the same program output, another clip
    assert len(argv(log)) == 3 and radio is not a


# ------------------------------------------------------------ voices
def test_system_voices_are_listed(tts):
    tts("say")
    assert speech.voices() == [("Samantha", "en_US"), ("Bad News", "en_US"), ("Paulina", "es_MX")]


def test_espeak_ng_voices_are_listed_by_language_and_name(tts):
    tts("espeak-ng")
    assert speech.voices() == [("en-us", "English_(America)"), ("es", "Spanish_(Spain)")]


@pytest.mark.parametrize("asked, used", [("Samantha", "Samantha"), ("samantha", "Samantha"), ("bad news", "Bad News")])
def test_known_voices_resolve_to_their_system_name(tts, asked, used):
    tts("say")
    assert speech.resolve_voice(asked) == (used, None)


def test_an_unknown_voice_falls_back_with_a_warning(tts):
    log = tts("say")
    voice, warning = speech.resolve_voice("Nobody")
    assert voice is None
    assert warning == 'unknown voice "Nobody"; using the default voice (see gentle-stream ctl say --list-voices)'
    assert not log.exists()


def test_no_voice_asked_is_no_warning(tts):
    tts("say")
    assert speech.resolve_voice(None) == (None, None)


# ------------------------------------------------------------ effects
def band_energy(x, lo, hi):
    mag = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return mag[(f >= lo) & (f < hi)].sum() / mag.sum()


def test_the_radio_effect_keeps_the_voice_band_only(tts):
    tts("say")
    dry, radio = speech.render("Hi"), speech.render("Hi", effect="radio")
    assert band_energy(dry, 0, 250) > 0.25 and band_energy(dry, 4500, 8000) > 0.25        # a third each
    assert band_energy(radio, 0, 250) < 0.05 and band_energy(radio, 4500, 8000) < 0.05   # only the 1 kHz is left


def test_the_space_effect_adds_a_reverb_tail(tts):
    tts("say")
    dry, space = speech.render("Hi"), speech.render("Hi", effect="space")
    assert len(space) > len(dry) + SR // 2                     # the room rings on after the phrase
    assert np.sqrt(np.mean(space[len(dry):] ** 2)) > 1e-3


@pytest.mark.parametrize("effect", EFFECTS)
def test_every_effect_keeps_the_phrase_level(tts, effect):
    tts("say")
    clip = speech.render("Hi", effect=effect)
    assert np.abs(clip).max() <= speech.SPEECH_PEAK + 1e-9
    assert np.sqrt(np.mean(clip ** 2)) > 0.5 * speech.SPEECH_RMS


def test_an_unknown_effect_is_refused(tts):
    tts("say")
    with pytest.raises(SpeechError, match="effect must be one of dry, radio, space"):
        speech.render("Hi", effect="echo")


# ------------------------------------------------------------ the player and the command
def test_the_player_passes_the_options_and_returns_the_warning(tts):
    from tests.test_daemon import fake_player

    log = tts("say")
    player = fake_player()
    answer = daemon.handle(player, {"cmd": "say", "text": "Hi", "voice": "Nobody", "rate": 200, "effect": "radio"})
    assert answer["ok"] is True
    assert answer["warnings"] == [('unknown voice "Nobody"; using the default voice (see gentle-stream ctl say '
                                   '--list-voices)')]
    assert argv(log)[0][3:] == ["--data-format=LEI16@22050", "-r", "200"]
    assert len(player.engine._speech_queue) == 1


@pytest.mark.parametrize("extra, error", [({"rate": "fast"}, "bad request: rate must be a whole number"),
                                         ({"voice": 3}, "bad request: voice must be a string"),
                                         ({"effect": "echo"}, "effect must be one of dry, radio, space")])
def test_bad_options_are_refused_by_the_player(tts, extra, error):
    from tests.test_daemon import fake_player

    tts("say")
    player = fake_player()
    assert daemon.handle(player, {"cmd": "say", "text": "Hi", **extra}) == {"ok": False, "error": error}
    assert player.engine._speech_queue == []


class FakeClient:
    def __init__(self, warnings=()):
        self.calls, self.warnings = [], list(warnings)

    def say(self, text, voice=None, rate=None, effect="dry"):
        self.calls.append((text, voice, rate, effect))
        return self.warnings

    def detach(self):
        pass


def test_ctl_say_passes_voice_rate_and_effect_and_prints_warnings(monkeypatch, capsys):
    from gentle_stream import client
    fake = FakeClient(['unknown voice "Nobody"; using the default voice (see gentle-stream ctl say --list-voices)'])
    monkeypatch.setattr(client, "connect", lambda: fake)
    assert main(["ctl", "say", "Almost", "there", "--voice", "Nobody", "--rate", "180", "--effect", "space"]) == 0
    assert fake.calls == [("Almost there", "Nobody", 180, "space")]
    assert capsys.readouterr() == ("", ('gentle-stream: warning: unknown voice "Nobody"; using the default voice (see '
                                        "gentle-stream ctl say --list-voices)\n"))


@pytest.mark.parametrize("args, message", [
    (["ctl", "say", "Hi", "--effect", "echo"], "invalid choice: 'echo'"),
    (["ctl", "say", "Hi", "--rate", "fast"], "invalid int value: 'fast'"),
    (["ctl", "say", "Hi", "--rate", "500"], f"--rate must be {RATES[0]} to {RATES[1]} words per minute"),
    (["ctl", "glide", "energy=0.5", "--voice", "Samantha"], "--voice, --rate, --effect and --sing are only for say"),
])
def test_ctl_option_errors_are_usage_errors(capsys, args, message):
    with pytest.raises(SystemExit) as e:
        main(args)
    assert e.value.code == 2 and message in capsys.readouterr().err


def test_list_voices_needs_no_player(tts, capsys, monkeypatch):
    from gentle_stream import client
    tts("say")
    monkeypatch.setattr(client, "connect", lambda: pytest.fail("contacted the player"))
    assert main(["ctl", "say", "--list-voices"]) == 0
    assert capsys.readouterr() == ("Samantha  en_US\nBad News  en_US\nPaulina  es_MX\n", "")


def test_list_voices_without_a_backend(tts, capsys):
    assert main(["ctl", "say", "--list-voices"]) == 1
    assert capsys.readouterr() == ("", f"gentle-stream: {speech.NO_BACKEND}\n")


def test_a_wav_with_extra_chunks_reads_without_warnings(tmp_path, recwarn):
    """`say` writes a chunk scipy does not know; reading it must not warn (it would fill the player's log)."""
    import struct
    pcm = (0.5 * np.sin(np.linspace(0, 200, 2205)) * 32767).astype("<i2").tobytes()
    fmt = struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"FLLR" + struct.pack("<I", 4) + b"\0" * 4 + \
        b"data" + struct.pack("<I", len(pcm)) + pcm
    path = tmp_path / "say.wav"
    path.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks)
    x, sr = speech.read_clip(path)
    assert sr == 22050 and len(x) == 2205
    assert [str(w.message) for w in recwarn] == []
