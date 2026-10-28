"""PM-028: SF2 voice packs (rendering tests skipped without FluidSynth and FluidR3_GM)."""
import json

import numpy as np
import pytest

from gentle_stream import main, samples, voicepacks
from gentle_stream.engine import Engine
from gentle_stream.style import Style
from gentle_stream.synth import SR
from gentle_stream.voicepacks import PackError, PackVoice, load_pack

REAL = samples.soundfont_path()
needs_sf2 = pytest.mark.skipif(REAL is None or samples.load_renderer(REAL) is None,
                               reason="FluidR3_GM or FluidSynth not installed (gentle-stream setup-samples)")
MANIFEST = {"name": "SF2 Choir", "license": "MIT", "source": "FluidR3_GM", "attribution": "Frank Wen",
            "redistributable": True}


@pytest.fixture(autouse=True)
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg" / "gentle-stream" / "voices.json"


def sf2_pack(folder, sf2, **fields):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pack.json").write_text(json.dumps({**MANIFEST, "sf2": str(sf2), **fields}))
    return folder


def run(capsys, *args):
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


# ------------------------------------------------------------ the manifest
def test_an_sf2_pack_names_its_file_bank_and_program(tmp_path, monkeypatch):
    monkeypatch.setattr(samples, "fluidsynth_module", lambda: object())
    folder = tmp_path / "pack"
    folder.mkdir()
    (folder / "voices.sf2").write_bytes(b"RIFF")
    pack = load_pack(sf2_pack(folder, "voices.sf2", bank=0, program=52))     # relative to the pack folder
    assert (pack.sf2, pack.bank, pack.program, pack.notes) == (folder / "voices.sf2", 0, 52, {})


def test_bank_and_program_default_to_zero_and_must_be_in_range(tmp_path, monkeypatch):
    monkeypatch.setattr(samples, "fluidsynth_module", lambda: object())
    sf2 = tmp_path / "v.sf2"
    sf2.write_bytes(b"RIFF")
    assert (load_pack(sf2_pack(tmp_path / "a", sf2)).bank, load_pack(sf2_pack(tmp_path / "a", sf2)).program) == (0, 0)
    for bad in ({"program": 128}, {"program": -1}, {"bank": 16384}, {"program": "52"}, {"bank": True}):
        with pytest.raises(PackError, match="must be a whole number"):
            load_pack(sf2_pack(tmp_path / "b", sf2, **bad))


def test_an_sf2_pack_still_needs_a_license(tmp_path, monkeypatch):
    monkeypatch.setattr(samples, "fluidsynth_module", lambda: object())
    sf2 = tmp_path / "v.sf2"
    sf2.write_bytes(b"RIFF")
    folder = sf2_pack(tmp_path / "p", sf2)
    data = json.loads((folder / "pack.json").read_text())
    del data["license"]
    (folder / "pack.json").write_text(json.dumps(data))
    with pytest.raises(PackError, match='has no "license"'):
        load_pack(folder)


def test_a_missing_or_non_sf2_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(samples, "fluidsynth_module", lambda: object())
    with pytest.raises(PackError, match="no such SF2 file"):
        load_pack(sf2_pack(tmp_path / "a", tmp_path / "missing.sf2"))
    other = tmp_path / "voices.sfz"
    other.write_text("<region>")
    with pytest.raises(PackError, match="must be an .sf2 file"):
        load_pack(sf2_pack(tmp_path / "b", other))


def test_without_fluidsynth_an_sf2_pack_is_refused_with_the_reason(tmp_path, capsys, config, monkeypatch):
    monkeypatch.setattr(samples, "fluidsynth_module", lambda: None)
    sf2 = tmp_path / "v.sf2"
    sf2.write_bytes(b"RIFF")
    code, out, err = run(capsys, "voices", "add", str(sf2_pack(tmp_path / "p", sf2)))
    assert (code, out) == (1, "")
    assert err == ("gentle-stream: FluidSynth is needed for SF2 voice packs (install the FluidSynth library and the "
                   "samples extra: uv sync --extra samples)\n")
    assert not config.exists()


def test_a_registered_sf2_pack_falls_back_when_fluidsynth_goes_away(tmp_path, capsys, monkeypatch, caplog):
    monkeypatch.setattr(samples, "fluidsynth_module", lambda: object())
    sf2 = tmp_path / "v.sf2"
    sf2.write_bytes(b"RIFF")
    run(capsys, "voices", "add", str(sf2_pack(tmp_path / "p", sf2)))
    monkeypatch.setattr(samples, "fluidsynth_module", lambda: None)
    assert voicepacks.active_voice() is None
    assert any("FluidSynth is needed for SF2 voice packs" in r.getMessage() for r in caplog.records)


def test_list_shows_the_sf2_program(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(samples, "fluidsynth_module", lambda: object())
    sf2 = tmp_path / "v.sf2"
    sf2.write_bytes(b"RIFF")
    folder = sf2_pack(tmp_path / "p", sf2, program=52)
    run(capsys, "voices", "add", str(folder))
    assert run(capsys, "voices", "list")[1] == (
        f"* SF2 Choir · license: MIT · by Frank Wen · source: FluidR3_GM · {sf2.name} program 52 · {folder}\n")


# ------------------------------------------------------------ rendering (real FluidSynth)
def direct(sf2, bank, program, midi, seconds):
    """The note as FluidSynth renders `program` itself, before level matching."""
    r = samples.load_renderer(sf2, SR)
    assert r is not None
    return samples._finish(r.note(0, bank, program, midi, voicepacks.SF2_VELOCITY, seconds, voicepacks.RELEASE), SR)


@needs_sf2
@pytest.mark.parametrize("program", [52, 53, 54])
def test_the_pack_renders_the_requested_program(tmp_path, program):
    voice = PackVoice(load_pack(sf2_pack(tmp_path / f"p{program}", REAL, program=program)))
    x = voice.note(60, 1.0)
    ref = direct(REAL, 0, program, 60, 1.0)
    n = min(len(x), len(ref))
    corr = np.dot(x[:n], ref[:n]) / (np.linalg.norm(x[:n]) * np.linalg.norm(ref[:n]))
    assert corr > 0.99                                    # the same sound, only scaled
    other = direct(REAL, 0, 0, 60, 1.0)                   # piano: a different program
    m = min(len(x), len(other))
    assert np.dot(x[:m], other[:m]) / (np.linalg.norm(x[:m]) * np.linalg.norm(other[:m])) < 0.9


@needs_sf2
def test_sf2_notes_are_level_matched_and_the_choir_sings_them(tmp_path, monkeypatch):
    from gentle_stream import vocals

    voice = PackVoice(load_pack(sf2_pack(tmp_path / "p", REAL, program=52)))
    x = voice.note(60, 1.0)
    rms = np.sqrt(np.mean(np.square(x[: SR // 2])))
    assert abs(20 * np.log10(rms / vocals.reference_rms(SR))) < 1.0
    monkeypatch.setattr(vocals, "sung", lambda *a, **k: pytest.fail("the procedural voice ran"))
    e = Engine(Style(voice=1.0), seed=3, samples=False, voices=voice)
    assert e.vocals_backend == "pack: SF2 Choir"
    out = np.concatenate([e.render_bar() for _ in range(2)])
    assert np.isfinite(out).all() and np.abs(out).max() < 1.0


@needs_sf2
def test_the_soundfont_loads_lazily_once_per_file(tmp_path, monkeypatch):
    calls = []
    real = samples.load_renderer
    monkeypatch.setattr(samples, "load_renderer", lambda path, sr=44100: calls.append(path) or real(path, sr))
    voice = PackVoice(load_pack(sf2_pack(tmp_path / "p", REAL, program=52)))
    assert calls == []                                    # registering or preparing the pack loads nothing
    voice.note(60, 1.0)
    voice.note(64, 1.0)
    assert calls == [REAL]
