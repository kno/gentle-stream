"""Piper with the carlfm voice for every phrase (local and broadcast): `setup-speech` installs the voice (pinned
revision, SHA-256, LICENSES.txt); the speech backend prefers Piper, then say, then espeak-ng (broadcasting: Piper or
espeak-ng); the text goes to stdin, never to the command line. One Piper process stays open and speaks every phrase
(loading the model takes seconds, a phrase then well under one). A fake `piper` program behaves as Piper 1.8's CLI
with `-d`: one line of stdin, one WAV in the folder, announced on stderr once written; nothing is downloaded."""
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from gentle_stream import main, speech, speechsetup

KEY_FILES = ("es_ES-carlfm-x_low.onnx", "es_ES-carlfm-x_low.onnx.json", "MODEL_CARD")

FAKE_PIPER = """#!{python} -I
import json, math, os, sys, time, wave
args = sys.argv[1:]
mode = os.environ.get("FAKE_PIPER_MODE", "")


def log(entry):
    with open({log!r}, "a") as f:
        f.write(json.dumps(entry) + "\\n")


log({{"start": args, "pid": os.getpid()}})
folder = args[args.index("-d") + 1]
for line in sys.stdin:
    text = line.rstrip("\\n")
    log({{"argv": args, "stdin": text}})
    if mode == "hang":
        time.sleep(60)
    if mode == "die":
        sys.exit(3)
    if mode == "slow":
        time.sleep(0.1)
    path = os.path.join(folder, f"{{time.time_ns()}}.wav")
    with wave.open(path, "wb") as w:   # as long as the text: 1000 samples a character, at 16 kHz
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"".join(int(8000 * math.sin(i / 8)).to_bytes(2, "little", signed=True)
                               for i in range(1000 * len(text))))
    log({{"wrote": path}})
    print(f"INFO:__main__:Wrote {{path}}", file=sys.stderr, flush=True)
log({{"exit": True}})
"""


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    speech.clear_cache()
    yield tmp_path / "cache" / "gentle-stream" / "speech"
    speech.use_only(None)
    speech.clear_cache()


def serve_carlfm(tmp_path, monkeypatch):
    """carlfm's three files served from a local folder, with their own hashes, in place of the pinned ones."""
    src = tmp_path / "src"
    src.mkdir()
    files = {}
    for name in KEY_FILES:
        data = {"MODEL_CARD": b"# Model card for carlfm\n* License: Public domain\n## Training\nTrained from scratch.\n",
                "es_ES-carlfm-x_low.onnx.json": json.dumps({"audio": {"sample_rate": 16000}}).encode()
                }.get(name, b"fake onnx weights " * 100)
        (src / name).write_bytes(data)
        files[name] = (f"{src.as_uri()}/{name}", hashlib.sha256(data).hexdigest())
    voice = speechsetup.SpeechVoice(**{**speechsetup.CATALOG["carlfm"].__dict__, "files": files})
    monkeypatch.setitem(speechsetup.CATALOG, "carlfm", voice)
    return voice


@pytest.fixture
def source(tmp_path, monkeypatch):
    return serve_carlfm(tmp_path, monkeypatch)


@pytest.fixture
def programs(tmp_path, monkeypatch):
    """Fake text-to-speech programs on a private PATH; returns (install, log)."""
    bin_dir, log = tmp_path / "bin", tmp_path / "tts.log"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    from tests.test_speech_voices import FAKE

    def install(*names):
        for name in names:
            path = bin_dir / name
            path.write_text((FAKE_PIPER if name == "piper" else FAKE).format(python=sys.executable, log=str(log)))
            path.chmod(0o755)
        speech.clear_cache()
    return install, log


def program() -> str | None:
    found = speech.backend()
    return found[0] if found else None


def entries(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def calls(log: Path) -> list[dict]:
    """Each phrase a program was given."""
    return [e for e in entries(log) if "stdin" in e]


def starts(log: Path) -> int:
    """How many times Piper was started."""
    return sum("start" in e for e in entries(log))


@pytest.fixture
def piper(source, programs):
    """Piper and carlfm installed; returns the log."""
    install, log = programs
    install("piper")
    speechsetup.setup_speech("carlfm")
    speech.clear_cache()
    return log


# ------------------------------------------------------------ the pinned voice
def test_the_catalog_pins_carlfm_at_a_revision_with_its_hashes():
    voice = speechsetup.CATALOG["carlfm"]
    assert voice.license == "Public domain (dataset), trained from scratch"
    for url, sha in voice.files.values():
        assert "/resolve/5041a7a49ae5b3a0f30e6837769eb03fdbb231bd/es/es_ES/carlfm/x_low/" in url and len(sha) == 64
    assert voice.files["es_ES-carlfm-x_low.onnx"][1] == \
        "d69677323a907cd4963f42b29c20a98b5d6bfa7f3e64df339915e4650c00d125"


def test_setup_downloads_verifies_and_keeps_the_licence(source, dirs):
    folder = speechsetup.setup_speech("carlfm")
    assert folder == dirs / "carlfm"
    assert sorted(p.name for p in folder.iterdir()) == sorted([*KEY_FILES, "LICENSES.txt"])
    licences = (folder / "LICENSES.txt").read_text()
    assert "Public domain" in licences and "SHA-256" in licences and "5041a7a" in licences
    assert speechsetup.installed() == {"carlfm": folder / "es_ES-carlfm-x_low.onnx"}
    assert speechsetup.setup_speech("carlfm") == folder                      # again: nothing downloaded


def test_an_unfinished_install_is_not_used_and_is_replaced_whole(source, dirs):
    folder = dirs / "carlfm"
    folder.mkdir(parents=True)
    for name in KEY_FILES:                                               # the files, but no LICENSES.txt
        (folder / name).write_bytes(b"left by an interrupted install")
    (folder / "stray.tmp").write_bytes(b"x")
    assert speechsetup.installed() == {}
    speechsetup.setup_speech("carlfm")
    assert sorted(p.name for p in folder.iterdir()) == sorted([*KEY_FILES, "LICENSES.txt"])
    assert (folder / "MODEL_CARD").read_bytes().startswith(b"# Model card")


def test_a_checksum_mismatch_leaves_nothing(source, dirs, monkeypatch):
    files = dict(source.files)
    files["MODEL_CARD"] = (files["MODEL_CARD"][0], "0" * 64)
    monkeypatch.setitem(speechsetup.CATALOG, "carlfm",
                        speechsetup.SpeechVoice(**{**source.__dict__, "files": files}))
    from gentle_stream.samples import ChecksumError

    with pytest.raises(ChecksumError, match="checksum mismatch"):
        speechsetup.setup_speech("carlfm")
    assert not dirs.exists() or list(dirs.rglob("*")) == []
    assert speechsetup.installed() == {}


def test_cli_setup_speech_says_where_and_what_to_install(source, capsys, programs):
    install, _ = programs
    assert main(["setup-speech"]) == 0
    out, err = capsys.readouterr()
    assert "installed" in out and "LICENSES.txt" in out and err == ""
    assert "the Piper program is not installed: uv tool install piper-tts" in out
    install("piper")
    assert main(["setup-speech", "carlfm"]) == 0
    out, _ = capsys.readouterr()
    assert out.startswith("carlfm already installed") and "Piper program" not in out


def test_cli_rejects_an_unknown_voice(capsys):
    with pytest.raises(SystemExit) as e:
        main(["setup-speech", "lessac"])
    assert e.value.code == 2


# ------------------------------------------------------------ speaking with it
def test_piper_comes_first_once_the_voice_and_program_are_there(source, programs):
    install, log = programs
    install("say", "espeak-ng")
    assert program() == "say"                                             # no Piper yet
    install("piper")
    assert program() == "say"                                             # the program, but no voice
    speechsetup.setup_speech("carlfm")
    speech.clear_cache()
    assert program() == "piper"
    speech.render("Respira hondo.", 22050)
    call = calls(log)[-1]
    assert call["stdin"] == "Respira hondo." and "Respira hondo." not in " ".join(call["argv"])
    model = call["argv"][call["argv"].index("-m") + 1]
    assert model.endswith("carlfm/es_ES-carlfm-x_low.onnx")


@pytest.mark.parametrize("rate, scale", [(None, None), (175, "1.0"), (350, "0.5"), (140, "1.25")])
def test_the_rate_becomes_pipers_length_scale(source, programs, rate, scale):
    install, log = programs
    install("piper")
    speechsetup.setup_speech("carlfm")
    speech.clear_cache()
    speech.render("Ya casi estamos.", 22050, rate=rate)
    argv = calls(log)[-1]["argv"]
    assert (argv[argv.index("--length-scale") + 1] if "--length-scale" in argv else None) == scale


def test_the_voices_list_and_resolve_know_carlfm(source, programs):
    install, _ = programs
    install("piper")
    speechsetup.setup_speech("carlfm")
    speech.clear_cache()
    assert speech.voices() == [("carlfm", "es_ES")]
    assert speech.resolve_voice("CARLFM") == ("carlfm", None)


def test_while_broadcasting_piper_is_used_and_say_never(source, programs):
    install, log = programs
    install("say", "piper")
    speechsetup.setup_speech("carlfm")
    speech.use_only(speech.BROADCAST_SAFE)
    assert program() == "piper" and speech.can_broadcast()
    speech.render("Sigue así.", 22050)
    assert "-m" in calls(log)[-1]["argv"]                                # Piper's call, not say's


def test_while_broadcasting_without_piper_espeak_ng_still_speaks(programs):
    install, _ = programs
    install("say", "espeak-ng")
    speech.use_only(speech.BROADCAST_SAFE)
    assert program() == "espeak-ng" and speech.can_broadcast()


def test_while_broadcasting_with_neither_the_reason_names_both(programs):
    install, _ = programs
    install("say")
    speech.use_only(speech.BROADCAST_SAFE)
    assert not speech.can_broadcast()
    with pytest.raises(speech.SpeechError) as e:
        speech.render("Hola.", 22050)
    assert str(e.value) == ("while broadcasting, phrases are spoken with Piper (gentle-stream setup-speech) or "
                            "espeak-ng (macOS voices are licensed for personal use only), and neither is installed")


# ------------------------------------------------------------ one Piper, kept open
def test_one_piper_process_speaks_every_phrase(piper):
    texts = ("Respira hondo.", "Ya casi estamos.", "Sigue así, vas muy bien.")
    clips = [speech.render(text, 16000) for text in texts]
    assert starts(piper) == 1
    assert [len(c) for c in clips] == [1000 * len(t) for t in texts]       # each phrase its own WAV
    assert [c["stdin"] for c in calls(piper)] == list(texts)


@pytest.mark.parametrize("mode", ["", "slow"])
def test_phrases_asked_for_at_once_each_get_their_own_clip(piper, monkeypatch, mode):
    monkeypatch.setenv("FAKE_PIPER_MODE", mode)
    texts = [f"Frase número {n}" + "." * n for n in range(6)]
    got = {}

    def speak(text):
        got[text] = len(speech.render(text, 16000))

    threads = [threading.Thread(target=speak, args=(t,)) for t in texts]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert got == {t: 1000 * len(t) for t in texts}
    assert starts(piper) == 1


def test_another_rate_starts_its_own_piper_and_the_first_stays(piper):
    speech.render("Uno.", 16000)
    speech.render("Dos.", 16000, rate=140)
    speech.render("Tres.", 16000)
    assert starts(piper) == 2
    assert [c["stdin"] for c in calls(piper)] == ["Uno.", "Dos.", "Tres."]


def test_warm_up_loads_piper_before_the_first_phrase(piper):
    speech.warm_up()
    deadline = time.monotonic() + 10
    while starts(piper) == 0 and time.monotonic() < deadline:   # the fake logs its start once it runs
        time.sleep(0.02)
    assert starts(piper) == 1 and calls(piper) == []
    speech.render("Respira hondo.", 16000)
    assert starts(piper) == 1


def test_warm_up_does_nothing_without_piper(programs):
    install, log = programs
    install("say")
    speech.warm_up()
    assert entries(log) == []


def test_a_piper_that_dies_is_reported_and_started_again(piper, monkeypatch):
    monkeypatch.setenv("FAKE_PIPER_MODE", "die")
    with pytest.raises(speech.SpeechError, match="^text-to-speech failed: piper exited 3"):
        speech.render("Uno.", 16000)
    monkeypatch.delenv("FAKE_PIPER_MODE")
    assert len(speech.render("Dos.", 16000)) == 4000
    assert starts(piper) == 2


def test_a_piper_that_hangs_times_out_and_is_stopped(piper, monkeypatch):
    import os

    monkeypatch.setattr(speech, "TIMEOUT", 1.0)
    monkeypatch.setattr(speech, "PIPER_STOP", 0.5)
    monkeypatch.setenv("FAKE_PIPER_MODE", "hang")
    with pytest.raises(speech.SpeechError, match="^text-to-speech failed: piper took more than 1 s"):
        speech.render("Uno.", 16000)
    hung = next(e["pid"] for e in entries(piper) if "start" in e)
    with pytest.raises(ProcessLookupError):                               # killed, not left behind
        os.kill(hung, 0)
    monkeypatch.delenv("FAKE_PIPER_MODE")
    assert len(speech.render("Dos.", 16000)) == 4000
    assert starts(piper) == 2


def test_a_phrase_leaves_no_file_behind(piper):
    speech.render("Uno.", 16000)
    wrote = [Path(e["wrote"]) for e in entries(piper) if "wrote" in e]
    assert len(wrote) == 1 and not wrote[0].exists()


def test_at_most_three_pipers_stay_open_the_least_recently_used_one_ends(piper):
    for rate in (100, 140, 200):
        speech.render("Uno.", 16000, rate=rate)
    speech.render("Dos.", 16000, rate=100)                                # 100 is now the most recently used
    assert sum("exit" in e for e in entries(piper)) == 0
    speech.render("Tres.", 16000, rate=300)                               # a fourth: 140 ends
    deadline = time.monotonic() + 10
    while not any("exit" in e for e in entries(piper)) and time.monotonic() < deadline:
        time.sleep(0.02)
    ended = [e for e in entries(piper) if "exit" in e]
    assert len(ended) == 1 and starts(piper) == 4
    speech.render("Cuatro.", 16000, rate=100)                             # still open
    assert starts(piper) == 4


def test_close_ends_every_piper(piper):
    speech.render("Uno.", 16000)
    speech.render("Dos.", 16000, rate=140)
    speech.close_piper()
    assert sum("exit" in e for e in entries(piper)) == 2


def test_help_lists_setup_speech(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "setup-speech" in capsys.readouterr().out

