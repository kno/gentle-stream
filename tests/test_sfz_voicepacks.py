"""PM-029: an SFZ subset for voice packs (synthetic SFZ and WAV fixtures)."""
import json
import logging

import numpy as np
import pytest
from scipy.io import wavfile

from gentle_stream import main, sfz, vocals
from gentle_stream.engine import Engine
from gentle_stream.style import Style
from gentle_stream.synth import SR
from gentle_stream.voicepacks import PackError, PackVoice, load_pack

MANIFEST = {"name": "SFZ Choir", "license": "CC0-1.0", "source": "made for the tests", "attribution": "Gentle Tester",
            "redistributable": True}

TABLE_SFZ = """// velocity layers over two key zones; every supported way of naming keys and paths
#define $LOW 48
<control> default_path=samples/
<global> ampeg_release=0.5
<group> lovel=1 hivel=63
<region> sample=soft low.wav lokey=$LOW hikey=59 pitch_keycenter=c4
<region> sample=soft high.wav lokey=c4 hikey=b4 pitch_keycenter=67
<group> lovel=64 hivel=127 volume=-3
<region> sample=loud low.wav lokey=$LOW hikey=59 pitch_keycenter=55
<region> sample=loud a.wav key=a4 /* a block
comment */ tune=-20
<region> sample=loud high.wav lokey=60 hikey=71 pitch_keycenter=67 hivel=100
"""
TABLE_SAMPLES = ("soft low", "soft high", "loud low", "loud a", "loud high")


@pytest.fixture(autouse=True)
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def sine(path, freq=441.0, seconds=0.5, sr=44100, silent_after=None):
    """A 0.5-amplitude sine; silent from sample `silent_after` on, as a recording that dies away after its loop
    (so a loop that joined anywhere but loop_end -> loop_start would step)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(seconds * sr)) / sr
    x = 0.5 * np.sin(2 * np.pi * freq * t)
    if silent_after is not None:
        x[silent_after:] = 0.0
    wavfile.write(path, sr, np.round(x * 32767).astype(np.int16))


def instrument(folder, text, samples=(), subdir=""):
    folder.mkdir(parents=True, exist_ok=True)
    for name in samples:
        sine(folder / subdir / f"{name}.wav")
    (folder / "choir.sfz").write_text(text)
    return folder / "choir.sfz"


def sfz_pack(folder, text, samples=(), subdir="", **fields):
    instrument(folder, text, samples, subdir)
    (folder / "pack.json").write_text(json.dumps({**MANIFEST, "sfz": "choir.sfz", **fields}))
    return folder


# ------------------------------------------------------------ parsing and region selection
@pytest.mark.parametrize("key, vel, expected", [
    (50, 30, "soft low"),     # lokey from a #define, soft layer
    (59, 63, "soft low"),     # both upper edges are inclusive
    (60, 30, "soft high"),    # lokey as a note name: c4 is 60
    (71, 1, "soft high"),     # b4 is 71, lowest velocity
    (50, 64, "loud low"),     # the loud group starts at velocity 64
    (69, 127, "loud a"),      # key=a4 sets lokey = hikey = 69
    (69, 90, "loud a"),       # "loud high" plays 69 at 90 too: the first matching region in the file wins
    (65, 90, "loud high"),    # the region's own hivel=100 narrows its group's 64-127
    (65, 110, None),          # ... so nothing answers 65 at velocity 110
    (47, 30, None),           # below every zone
    (72, 100, None),          # above every zone
])
def test_region_selection_by_key_and_velocity_matches_the_table(tmp_path, key, vel, expected):
    inst = sfz.parse(instrument(tmp_path / "i", TABLE_SFZ, TABLE_SAMPLES, "samples"))
    region = inst.region(key, vel)
    assert (region.sample.stem if region else None) == expected


def test_opcodes_are_inherited_from_global_and_group_and_overridden_by_the_region(tmp_path):
    inst = sfz.parse(instrument(tmp_path / "i", TABLE_SFZ, TABLE_SAMPLES, "samples"))
    by_name = {r.sample.stem: r for r in inst.regions}
    assert all(r.ampeg_release == 0.5 for r in inst.regions)                  # <global>
    assert [by_name[n].volume for n in TABLE_SAMPLES] == [0, 0, -3, -3, -3]    # <group> volume=-3
    assert (by_name["loud a"].lokey, by_name["loud a"].hikey, by_name["loud a"].pitch_keycenter) == (69, 69, 69)
    assert by_name["loud a"].tune == -20
    assert (by_name["loud high"].lovel, by_name["loud high"].hivel) == (64, 100)
    assert by_name["soft low"].sample == tmp_path / "i" / "samples" / "soft low.wav"   # default_path, spaces


@pytest.mark.parametrize("name, midi", [("c4", 60), ("C#4", 61), ("db4", 61), ("a-1", 9), ("60", 60), ("b3", 59)])
def test_sfz_note_names_put_middle_c_at_c4(name, midi):
    assert sfz.key(name) == midi


def test_unsupported_opcodes_are_reported_once(tmp_path, caplog):
    text = "<region> sample=a.wav cutoff=500 fil_type=lpf_2p\n<region> sample=a.wav cutoff=600 lokey=61\n"
    with caplog.at_level(logging.WARNING, logger="gentle_stream.sfz"):
        inst = sfz.parse(instrument(tmp_path / "i", text, ("a",)))
    assert len(inst.regions) == 2
    assert [r.getMessage() for r in caplog.records] == [
        f"{tmp_path / 'i' / 'choir.sfz'}: unsupported opcodes ignored: cutoff, fil_type"]


def test_only_wav_samples_are_accepted(tmp_path):
    folder = tmp_path / "i"
    folder.mkdir()
    (folder / "a.flac").write_bytes(b"fLaC")
    (folder / "choir.sfz").write_text("<region> sample=a.flac\n")
    with pytest.raises(PackError, match=r"unsupported format: convert to WAV \(a.flac\)"):
        sfz.parse(folder / "choir.sfz")


def test_a_missing_sample_or_an_empty_instrument_is_refused(tmp_path):
    with pytest.raises(PackError, match="no such sample"):
        sfz.parse(instrument(tmp_path / "a", "<region> sample=gone.wav\n"))
    with pytest.raises(PackError, match="has no <region>"):
        sfz.parse(instrument(tmp_path / "b", "<group> volume=-3\n"))


def test_bad_opcode_values_are_refused_with_the_line(tmp_path):
    with pytest.raises(PackError, match=r"line 1: lokey=low"):
        sfz.parse(instrument(tmp_path / "a", "<region> sample=a.wav lokey=low\n", ("a",)))


# ------------------------------------------------------------ sustain loops and articulation
def pitch(x, target):
    from scipy.signal import correlate
    x = x - np.mean(x)
    corr = correlate(x, x, mode="full", method="fft")[len(x) - 1:]
    lo, hi = int(SR / (target * 1.3)), int(SR / (target / 1.3))
    k = lo + int(np.argmax(corr[lo:hi]))
    a, b, c = corr[k - 1:k + 2]
    return SR / (k + 0.5 * (a - c) / (a - 2 * b + c))


# 110 whole periods starting a quarter period in, where the sine is at its crest: the join only matches loop_start
LOOPED = "<region> sample=a.wav pitch_keycenter=69 loop_mode=loop_continuous loop_start=11025 loop_end=22024\n"


@pytest.mark.parametrize("midi", [69, 71])     # at the recorded pitch and shifted: the loop joins either way
def test_sustain_loops_hold_notes_longer_than_the_sample_without_clicks(tmp_path, midi):
    folder = sfz_pack(tmp_path / "p", LOOPED, ())
    sine(folder / "a.wav", seconds=0.6, silent_after=22025)    # silence right after loop_end
    voice = PackVoice(load_pack(folder))
    x = voice.note(midi, 3.0)                                  # the recording lasts 0.5 s
    assert len(x) >= int(3.0 * SR)
    early = np.sqrt(np.mean(np.square(x[int(0.1 * SR):int(0.4 * SR)])))
    held = np.sqrt(np.mean(np.square(x[int(2.0 * SR):int(2.9 * SR)])))
    assert abs(held / early - 1) < 0.05                        # still singing, as loud
    freq = 441.0 * 2 ** ((midi - 69) / 12)
    steady = x[int(0.1 * SR):int(2.9 * SR)]
    bound = np.abs(steady).max() * 2 * np.pi * freq / SR      # the steepest step a sine of this pitch takes
    assert np.abs(np.diff(steady)).max() <= 1.05 * bound       # no step anywhere: the loop joins smoothly
    assert abs(1200 * np.log2(pitch(x[int(2.0 * SR):int(2.5 * SR)], freq) / freq)) < 10


def test_a_sample_without_a_loop_ends_with_its_recording(tmp_path):
    voice = PackVoice(load_pack(sfz_pack(tmp_path / "p", "<region> sample=a.wav pitch_keycenter=69\n", ("a",))))
    x = voice.note(69, 3.0)
    assert len(x) <= int(0.5 * SR) + 1 and x[-1] == 0


def test_loop_sustain_and_one_shot_modes(tmp_path):
    held = sfz.parse(instrument(tmp_path / "a", LOOPED.replace("loop_continuous", "loop_sustain"), ("a",)))
    assert held.regions[0].loops
    shot = sfz.parse(instrument(tmp_path / "b", LOOPED.replace("loop_continuous", "one_shot"), ("a",)))
    assert not shot.regions[0].loops
    default = sfz.parse(instrument(tmp_path / "c", LOOPED.replace(" loop_mode=loop_continuous", ""), ("a",)))
    assert default.regions[0].loops                             # loop points given: they loop


def test_tune_and_pitch_keycenter_set_the_pitch_within_10_cents(tmp_path):
    text = "<region> sample=a.wav pitch_keycenter=69 tune=-50 loop_mode=loop_continuous loop_start=11025 loop_end=22024\n"
    voice = PackVoice(load_pack(sfz_pack(tmp_path / "p", text, ("a",))))
    for midi in (65, 69, 73):
        x = voice.note(midi, 1.0)
        target = 441.0 * 2 ** ((midi - 69) / 12) * 2 ** (-50 / 1200)  # tune=-50 lowers the playback 50 cents
        assert abs(1200 * np.log2(pitch(x[int(0.2 * SR):int(0.8 * SR)], target) / target)) < 10


def test_attack_release_and_volume_shape_the_note(tmp_path):
    text = ("<region> sample=a.wav pitch_keycenter=69 ampeg_attack=0.1 ampeg_release=0.2 volume=-6 "
            "loop_mode=loop_continuous loop_start=11025 loop_end=22024\n")
    quiet = PackVoice(load_pack(sfz_pack(tmp_path / "q", text, ("a",))))
    loud = PackVoice(load_pack(sfz_pack(tmp_path / "l", text.replace(" volume=-6", ""), ("a",))))
    x, y = quiet.note(69, 1.0), loud.note(69, 1.0)
    assert len(x) == int(1.2 * SR)                                       # 0.2 s release
    ramp = np.abs(x[: int(0.1 * SR)]).max()
    assert np.abs(x[: int(0.01 * SR)]).max() < 0.15 * np.abs(x).max() and ramp > 0.5 * np.abs(x).max()
    ratio = np.sqrt(np.mean(x[SR // 2:int(0.9 * SR)] ** 2)) / np.sqrt(np.mean(y[SR // 2:int(0.9 * SR)] ** 2))
    assert abs(20 * np.log10(ratio) + 6) < 0.1


# ------------------------------------------------------------ the pack
def test_an_sfz_pack_loads_lists_and_sings(tmp_path, capsys, monkeypatch):
    folder = sfz_pack(tmp_path / "p", TABLE_SFZ, TABLE_SAMPLES, "samples")
    pack = load_pack(folder)
    assert pack.sfz == folder / "choir.sfz" and len(pack.regions) == 5
    assert main(["voices", "add", str(folder)]) == 0
    capsys.readouterr()
    assert main(["voices", "list"]) == 0
    assert capsys.readouterr().out == (f"* SFZ Choir · license: CC0-1.0 · by Gentle Tester · source: made for the "
                                       f"tests · choir.sfz (5 regions) · {folder}\n")
    monkeypatch.setattr(vocals, "sung", lambda *a, **k: pytest.fail("the procedural voice ran"))
    e = Engine(Style(voice=1.0), seed=3, samples=False, voices=PackVoice(pack))
    assert e.vocals_backend == "pack: SFZ Choir"
    out = np.concatenate([e.render_bar() for _ in range(2)])
    assert np.isfinite(out).all() and np.abs(out).max() < 1.0


def test_a_note_no_region_answers_sings_the_nearest_zone_and_is_reported_once(tmp_path, caplog):
    voice = PackVoice(load_pack(sfz_pack(tmp_path / "p", TABLE_SFZ, TABLE_SAMPLES, "samples")))
    with caplog.at_level(logging.WARNING, logger="gentle_stream.voicepacks"):
        a = voice.note(40, 1.0)
        voice.note(40, 0.5)
    assert np.abs(a).max() > 0
    assert [r.getMessage() for r in caplog.records] == [
        'voice pack "SFZ Choir": no region plays note 40 at velocity 80; the nearest one sings it']


def test_an_sfz_pack_still_needs_a_license_and_a_real_file(tmp_path):
    folder = sfz_pack(tmp_path / "p", TABLE_SFZ, TABLE_SAMPLES, "samples")
    data = json.loads((folder / "pack.json").read_text())
    (folder / "pack.json").write_text(json.dumps({k: v for k, v in data.items() if k != "license"}))
    with pytest.raises(PackError, match='has no "license"'):
        load_pack(folder)
    (folder / "pack.json").write_text(json.dumps({**data, "sfz": "other.sfz"}))
    with pytest.raises(PackError, match="no such SFZ file"):
        load_pack(folder)
