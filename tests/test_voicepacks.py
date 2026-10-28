"""PM-027: WAV voice packs with licensing and attribution (synthetic WAV fixtures, never real recordings)."""
import json
import logging

import numpy as np
import pytest
from scipy.io import wavfile
from scipy.signal import correlate

from gentle_stream import main, vocals, voicepacks
from gentle_stream.engine import Engine
from gentle_stream.style import Style
from gentle_stream.synth import SR, mtof, osc
from gentle_stream.voicepacks import (
    MAX_SHIFT,
    PackError,
    VoiceStore,
    load_pack,
    note_number,
)

MANIFEST = {"name": "Test Choir", "license": "CC0-1.0", "source": "made for the tests",
            "attribution": "Gentle Tester", "redistributable": True, "root_note_from_filename": True}


@pytest.fixture(autouse=True)
def config(monkeypatch, tmp_path):
    """No test may touch the real ~/.config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg" / "gentle-stream" / "voices.json"


def make_pack(folder, manifest=MANIFEST, notes=("A3", "A4"), sr=44100, dtype="int16", channels=1, seconds=2.0):
    """A pack folder: `pack.json` plus one saw tone per note name, written as `dtype` WAV at `sr`."""
    folder.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (folder / "pack.json").write_text(json.dumps(manifest))
    for name in notes:
        x = 0.5 * osc("saw", mtof(note_number(name)), int(seconds * sr), sr)
        x = np.stack([x] * channels, axis=1) if channels > 1 else x
        if dtype == "int16":
            data = np.round(x * 32767).astype(np.int16)
        elif dtype == "int32":                       # how scipy reads 24-bit files: the value in the top 24 bits
            data = (np.round(x * 8388607).astype(np.int32) << 8)
        else:
            data = x.astype(np.float32)
        wavfile.write(folder / f"{name}.wav", sr, data)
    return folder


def pitch(x, target):
    x = x - np.mean(x)
    corr = correlate(x, x, mode="full", method="fft")[len(x) - 1:]
    lo, hi = int(SR / (target * 1.3)), int(SR / (target / 1.3))
    k = lo + int(np.argmax(corr[lo:hi]))
    a, b, c = corr[k - 1:k + 2]
    return SR / (k + 0.5 * (a - c) / (a - 2 * b + c))


def run(capsys, *args):
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


# ------------------------------------------------------------ the manifest and the files
def test_note_names_map_to_midi_numbers():
    assert [note_number(n) for n in ("C4", "A4", "A#3", "Bb3", "D2", "c-1")] == [60, 69, 58, 58, 38, 0]


def test_a_pack_without_a_license_is_refused_with_a_clear_message(tmp_path, capsys, config):
    folder = make_pack(tmp_path / "nolicense", {k: v for k, v in MANIFEST.items() if k != "license"})
    with pytest.raises(PackError, match='has no "license"'):
        load_pack(folder)
    code, out, err = run(capsys, "voices", "add", str(folder))
    assert code == 1 and out == ""
    assert err == (f'gentle-stream: {folder / "pack.json"} has no "license": every voice pack must say how its '
                   "recordings may be used\n")
    assert not config.exists()                       # nothing registered


@pytest.mark.parametrize("license_value", ["", "   ", 42, None])
def test_an_empty_or_non_text_license_is_refused_too(tmp_path, license_value):
    with pytest.raises(PackError, match='has no "license"'):
        load_pack(make_pack(tmp_path / "bad", {**MANIFEST, "license": license_value}))


def test_a_folder_without_a_manifest_is_refused(tmp_path):
    with pytest.raises(PackError, match="no pack.json"):
        load_pack(make_pack(tmp_path / "bare", None))


@pytest.mark.parametrize("ext", ["flac", "ogg", "FLAC"])
def test_flac_and_ogg_files_are_refused_with_a_conversion_hint(tmp_path, capsys, config, ext):
    folder = make_pack(tmp_path / "compressed")
    (folder / f"C4.{ext}").write_bytes(b"not decoded")
    code, out, err = run(capsys, "voices", "add", str(folder))
    assert code == 1 and out == ""
    assert err == f"gentle-stream: unsupported format: convert to WAV (C4.{ext})\n"
    assert not config.exists()


def test_a_pack_needs_note_named_wav_files(tmp_path):
    folder = make_pack(tmp_path / "empty", notes=())
    (folder / "readme.txt").write_text("no audio here")
    with pytest.raises(PackError, match="no note-named WAV"):
        load_pack(folder)


@pytest.mark.parametrize("dtype, channels", [("int16", 1), ("int32", 1), ("float32", 1), ("int16", 2)])
def test_16_and_24_bit_float_mono_and_stereo_wavs_load(tmp_path, dtype, channels):
    pack = load_pack(make_pack(tmp_path / f"{dtype}{channels}", dtype=dtype, channels=channels))
    assert sorted(pack.notes) == [57, 69]
    x = voicepacks.PackVoice(pack).note(57, 1.0)
    assert x.ndim == 1 and np.isfinite(x).all() and 0 < np.abs(x).max() <= 1.0


# ------------------------------------------------------------ pitch
@pytest.mark.parametrize("shift", range(-MAX_SHIFT, MAX_SHIFT + 1))
@pytest.mark.parametrize("file_sr", [44100, 48000])
def test_shifted_notes_are_within_10_cents(tmp_path, shift, file_sr):
    voice = voicepacks.PackVoice(load_pack(make_pack(tmp_path / "p", notes=("A3",), sr=file_sr)))
    midi = 57 + shift
    x = voice.note(midi, 1.0)
    measured = pitch(x[int(0.2 * SR):int(0.8 * SR)], mtof(midi))
    assert abs(1200 * np.log2(measured / mtof(midi))) < 10


def test_the_nearest_recorded_note_is_used(tmp_path):
    voice = voicepacks.PackVoice(load_pack(make_pack(tmp_path / "p", notes=("A3", "A4"))))
    assert voice.source(59) == (57, 2) and voice.source(66) == (69, -3)


def test_notes_within_the_shift_limit_of_a_recording_are_not_reported(tmp_path, caplog):
    voice = voicepacks.PackVoice(load_pack(make_pack(tmp_path / "p", notes=("A3",))))
    with caplog.at_level(logging.WARNING, logger="gentle_stream.voicepacks"):
        for midi in range(57 - MAX_SHIFT, 57 + MAX_SHIFT + 1):
            assert voice.source(midi) == (57, midi - 57)
    assert caplog.records == []


def test_notes_outside_the_recorded_range_fold_by_octaves_and_are_reported_once(tmp_path, caplog):
    voice = voicepacks.PackVoice(load_pack(make_pack(tmp_path / "p", notes=("A3",))))
    with caplog.at_level(logging.WARNING, logger="gentle_stream.voicepacks"):
        assert voice.source(81) == (57, 0)              # A5: folded two octaves onto A3, still an A
        assert voice.source(81) == (57, 0)
        assert voice.source(83) == (57, 2)              # B5 sings B3
    reports = [r.getMessage() for r in caplog.records]
    assert reports == ['voice pack "Test Choir": note 81 is outside its recorded range (57-57); it sings 57 instead',
                       'voice pack "Test Choir": note 83 is outside its recorded range (57-57); it sings 59 instead']


def test_a_note_far_from_every_recording_takes_the_smallest_shift_and_is_reported(tmp_path, caplog):
    voice = voicepacks.PackVoice(load_pack(make_pack(tmp_path / "p", notes=("A3",))))
    with caplog.at_level(logging.WARNING, logger="gentle_stream.voicepacks"):
        assert voice.source(63) == (57, 6)              # D#4: a tritone from A3 either way
        assert voice.source(52) == (57, -5)
    assert [r.getMessage() for r in caplog.records] == [
        'voice pack "Test Choir": note 63 is 6 semitones from its nearest recording (57); it may sound unnatural',
        'voice pack "Test Choir": note 52 is 5 semitones from its nearest recording (57); it may sound unnatural']


def test_every_note_keeps_its_pitch_class(tmp_path):
    voice = voicepacks.PackVoice(load_pack(make_pack(tmp_path / "p", notes=("A3",))))
    for midi in range(24, 108):
        root, shift = voice.source(midi)
        assert abs(shift) <= 6 and (root + shift - midi) % 12 == 0


def test_notes_swell_in_and_release_without_clicks(tmp_path):
    voice = voicepacks.PackVoice(load_pack(make_pack(tmp_path / "p", notes=("A3",), seconds=0.5)))
    x = voice.note(57, 2.0)                             # longer than the recording: it ends with it, faded
    ramp = int(voicepacks.ATTACK * SR)
    bound = np.abs(x).max() * (np.arange(ramp) / ramp) + 1e-9
    assert x[0] == 0 and np.all(np.abs(x[:ramp]) <= bound)   # a linear swell from silence: no click
    fade = int(0.01 * SR)                                     # the recording runs out: a 10 ms fade to silence
    assert x[-1] == 0 and np.all(np.abs(x[-fade:]) <= np.abs(x).max() * np.linspace(1, 0, fade) + 1e-9)


# ------------------------------------------------------------ the registry and the CLI
def test_add_registers_the_folder_without_copying_and_makes_it_the_choir(tmp_path, capsys, config):
    folder = make_pack(tmp_path / "choir")
    code, out, err = run(capsys, "voices", "add", str(folder))
    assert (code, err) == (0, "")
    assert out == 'Added voice pack "Test Choir" (CC0-1.0); the choir now sings it\n'
    data = json.loads(config.read_text())
    assert data == {"version": 1, "active": "Test Choir", "packs": [{"name": "Test Choir", "path": str(folder)}]}
    assert list(config.parent.iterdir()) == [config]   # nothing copied
    active = VoiceStore().active()
    assert active is not None and active.name == "Test Choir"


def test_list_prints_license_and_attribution_for_every_pack(tmp_path, capsys):
    a = make_pack(tmp_path / "a")
    b = make_pack(tmp_path / "b", {**MANIFEST, "name": "Other", "license": "CC-BY-4.0", "attribution": "Someone",
                                     "source": "https://example.org/other", "redistributable": False})
    run(capsys, "voices", "add", str(a))
    run(capsys, "voices", "add", str(b))
    code, out, err = run(capsys, "voices", "list")
    assert (code, err) == (0, "")
    assert out == (f"  Test Choir · license: CC0-1.0 · by Gentle Tester · source: made for the tests · {a}\n"
                   f"* Other · license: CC-BY-4.0 · by Someone · source: https://example.org/other · {b}\n")


def test_list_without_packs_says_how_to_add_one(capsys):
    assert run(capsys, "voices", "list") == (0, "No voice packs. Add one with: gentle-stream voices add FOLDER\n", "")


def test_list_reports_a_registered_pack_that_no_longer_loads(tmp_path, capsys):
    folder = make_pack(tmp_path / "gone")
    run(capsys, "voices", "add", str(folder))
    (folder / "pack.json").unlink()
    code, out, _ = run(capsys, "voices", "list")
    assert code == 0 and out == f"* Test Choir · unavailable: {folder} has no pack.json\n"


def test_adding_the_same_name_again_replaces_its_folder(tmp_path, capsys, config):
    run(capsys, "voices", "add", str(make_pack(tmp_path / "v1")))
    newer = make_pack(tmp_path / "v2")
    code, out, _ = run(capsys, "voices", "add", str(newer))
    assert code == 0 and out == 'Replaced voice pack "Test Choir" (CC0-1.0); the choir now sings it\n'
    assert json.loads(config.read_text())["packs"] == [{"name": "Test Choir", "path": str(newer)}]


def test_remove_returns_the_choir_to_its_own_voice(tmp_path, capsys, config):
    run(capsys, "voices", "add", str(make_pack(tmp_path / "choir")))
    assert run(capsys, "voices", "remove", "test choir") == (0, 'Removed voice pack "Test Choir"\n', "")
    assert json.loads(config.read_text()) == {"version": 1, "active": None, "packs": []}
    assert VoiceStore().active() is None
    assert run(capsys, "voices", "remove", "Test Choir") == (1, "", 'gentle-stream: no voice pack called "Test Choir"\n')


def test_a_missing_folder_is_refused(tmp_path, capsys, config):
    code, out, err = run(capsys, "voices", "add", str(tmp_path / "nowhere"))
    assert (code, out) == (1, "") and err == f"gentle-stream: {tmp_path / 'nowhere'} is not a folder\n"
    assert not config.exists()


def test_help_lists_the_voices_command(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "voices" in capsys.readouterr().out


# ------------------------------------------------------------ the choir sings the pack
def test_the_engine_choir_sings_the_active_pack(tmp_path, monkeypatch):
    voice = voicepacks.PackVoice(load_pack(make_pack(tmp_path / "choir")))
    sung = []
    real = voice.note
    monkeypatch.setattr(voice, "note", lambda m, s: sung.append(m) or real(m, s))
    monkeypatch.setattr(vocals, "sung", lambda *a, **k: pytest.fail("the procedural voice ran"))
    e = Engine(Style(voice=1.0), seed=3, samples=False, voices=voice)
    assert e.vocals_backend == "pack: Test Choir"
    x = np.concatenate([e.render_bar() for _ in range(2)])
    assert sung and np.isfinite(x).all() and np.abs(x).max() < 1.0


def test_only_a_pack_marked_for_melody_enables_the_vocal_melody(tmp_path):
    plain = voicepacks.PackVoice(load_pack(make_pack(tmp_path / "plain")))
    singer = voicepacks.PackVoice(load_pack(make_pack(tmp_path / "singer", {**MANIFEST, "melody": True})))
    assert Engine(Style(voice=0.8), seed=3, samples=False, voices=plain).melodic_vocals is False
    assert Engine(Style(voice=0.8), seed=3, samples=False, voices=singer).melodic_vocals is True
    assert Engine(Style(voice=0.8), seed=3, samples=False).melodic_vocals is False


def test_active_voice_loads_the_registered_pack_or_falls_back(tmp_path, capsys, caplog):
    assert voicepacks.active_voice() is None
    folder = make_pack(tmp_path / "choir")
    run(capsys, "voices", "add", str(folder))
    voice = voicepacks.active_voice()
    assert voice is not None and voice.pack.name == "Test Choir"
    (folder / "pack.json").unlink()                    # broken since it was added: the built-in choir sings
    with caplog.at_level(logging.WARNING, logger="gentle_stream.voicepacks"):
        assert voicepacks.active_voice() is None
    assert any("unavailable" in r.getMessage() for r in caplog.records)


def test_render_uses_the_active_pack_unless_procedural(tmp_path, capsys, monkeypatch):
    run(capsys, "voices", "add", str(make_pack(tmp_path / "choir")))
    seen = []
    real = Engine.__init__

    def spy(self, *a, **k):
        seen.append(k.get("voices"))
        real(self, *a, **k)

    monkeypatch.setattr(Engine, "__init__", spy)
    out = tmp_path / "x.wav"
    assert main(["render", "--seconds", "1", "--seed", "1", str(out)]) == 0
    assert main(["render", "--seconds", "1", "--seed", "1", "--procedural", str(out)]) == 0
    assert seen[0] is not None and seen[0].pack.name == "Test Choir"
    assert seen[1] is None
