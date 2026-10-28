"""PM-030: `setup-voices` installs a CC0 voice pack with the same guarantees as `setup-samples`.

Every test builds a small local archive shaped like the FreePats release (a top folder with a space in its name, an
SFZ, WAV samples, LICENSE.txt and README.txt) and serves it through a file:// URL: nothing is downloaded.
"""
import hashlib
import json
import shutil
import subprocess

import numpy as np
import pytest
from scipy.io import wavfile

from gentle_stream import main, voicepacks, voicesetup
from gentle_stream.samples import ChecksumError, SetupError
from gentle_stream.voicesetup import CATALOG, Source, setup_voices

needs_bsdtar = pytest.mark.skipif(shutil.which("bsdtar") is None, reason="bsdtar is needed to build the test archive")
TOP = "SynthPadChoir SFZ+WAV-20200516"
SFZ_NAME = "SynthPadChoir 20200516.sfz"
SFZ = """//+ Name: Synth Pad Choir
<global>
 ampeg_release=2
 loop_mode=loop_continuous

<group>
<region>
 lokey=33 hikey=62
 pitch_keycenter=60
 loop_start=1000 loop_end=4999
 sample=samples/C4.wav
<region>
 lokey=63 hikey=108
 pitch_keycenter=66
 loop_start=1000 loop_end=4999
 sample=samples/F#4.wav
"""
LICENSE = "Creative Commons Legal Code\n\nCC0 1.0 Universal\n"
README = "Synth Pad Choir\nSamples by Elf of Happy and Love. Published under CC0.\n"


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    """Private config and cache dirs: no test touches ~/.config or ~/.cache."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path / "cache" / "gentle-stream" / "voices"


def make_archive(path, files: dict[str, str] | None = None, sfz: str = SFZ, license_text: str | None = LICENSE):
    """A FreePats-shaped .7z at `path`; returns (file:// URL, sha256). `files` replaces the default members."""
    src = path.parent / f"{path.stem}-src"
    top = src / TOP
    (top / "samples").mkdir(parents=True)
    if files is None:
        files = {SFZ_NAME: sfz, "README.txt": README}
        if license_text is not None:
            files["LICENSE.txt"] = license_text
        t = np.arange(6000) / 44100
        for name, freq in (("C4", 261.63), ("F#4", 369.99)):
            wavfile.write(top / "samples" / f"{name}.wav", 44100,
                          np.round(0.5 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16))
    for name, text in files.items():
        (top / name).parent.mkdir(parents=True, exist_ok=True)
        (top / name).write_text(text)
    subprocess.run(["bsdtar", "--format", "7zip", "-cf", str(path), "-C", str(src), TOP], check=True)
    shutil.rmtree(src)
    return path.as_uri(), hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def source(tmp_path, monkeypatch):
    """The catalog entry pointed at a local archive."""
    url, sha = make_archive(tmp_path / "choir.7z")
    entry = Source(**{**CATALOG["freepats-synth-choir"].__dict__, "url": url, "sha256": sha})
    monkeypatch.setitem(CATALOG, "freepats-synth-choir", entry)
    return entry


def run(capsys, *args):
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


# ------------------------------------------------------------ the pinned source
def test_the_pinned_source_is_the_inspected_freepats_release():
    entry = CATALOG["freepats-synth-choir"]
    assert entry.url == ("https://github.com/freepats/synth-pad-choir/releases/download/2020-05-16/"
                         "SynthPadChoir-SFZ+WAV-20200516.7z")
    assert entry.sha256 == "19f94afc8aed5e120b444da668a51a1737a1e87b772ae93b495d0fc42ff92a16"
    assert entry.license == "CC0-1.0" and "Elf of Happy and Love" in entry.attribution


# ------------------------------------------------------------ install
@needs_bsdtar
def test_setup_downloads_verifies_extracts_and_registers_the_pack(source, dirs):
    folder = setup_voices("freepats-synth-choir")
    assert folder == dirs / "freepats-synth-choir"
    assert sorted(p.name for p in folder.iterdir()) == ["LICENSE.txt", "LICENSES.txt", "README.txt", SFZ_NAME,
                                                       "pack.json", "samples"]
    manifest = json.loads((folder / "pack.json").read_text())
    assert manifest == {"name": "FreePats Synth Pad Choir", "license": "CC0-1.0", "source": source.url,
                        "attribution": source.attribution, "redistributable": True, "sfz": SFZ_NAME}
    pack = voicepacks.VoiceStore().active()
    assert pack is not None and pack.name == "FreePats Synth Pad Choir" and len(pack.regions) == 2
    x = voicepacks.PackVoice(pack).note(64, 1.0)                    # it sings, loop held past the 0.14 s sample
    assert np.isfinite(x).all() and len(x) > 44100
    assert [p.name for p in dirs.iterdir()] == ["freepats-synth-choir"]   # no partial files left


@needs_bsdtar
def test_licenses_file_records_source_checksum_credit_and_the_archive_texts(source, dirs):
    folder = setup_voices("freepats-synth-choir")
    text = (folder / "LICENSES.txt").read_text()
    for expected in (source.url, source.sha256, "CC0-1.0", source.attribution, LICENSE, README):
        assert expected in text


@needs_bsdtar
def test_setup_is_idempotent_and_never_downloads_twice(source, dirs, monkeypatch):
    first = setup_voices("freepats-synth-choir")
    stamp = (first / "LICENSES.txt").stat().st_mtime_ns
    monkeypatch.setattr(voicesetup, "_download", lambda *a, **k: pytest.fail("downloaded twice"))
    assert setup_voices("freepats-synth-choir") == first
    assert (first / "LICENSES.txt").stat().st_mtime_ns == stamp
    assert [p["name"] for p in json.loads(voicepacks.default_path().read_text())["packs"]] == [
        "FreePats Synth Pad Choir"]


# ------------------------------------------------------------ failures leave nothing behind
def nothing_behind(dirs):
    assert not dirs.exists() or list(dirs.iterdir()) == []
    assert not voicepacks.default_path().exists()


@needs_bsdtar
def test_checksum_mismatch_is_rejected_and_leaves_nothing_behind(source, dirs, monkeypatch):
    monkeypatch.setitem(CATALOG, "freepats-synth-choir",
                        Source(**{**source.__dict__, "sha256": "0" * 64}))
    with pytest.raises(ChecksumError, match="checksum mismatch"):
        setup_voices("freepats-synth-choir")
    nothing_behind(dirs)


@needs_bsdtar
@pytest.mark.parametrize("build, message", [
    (lambda p: make_archive(p, license_text=None), "has no LICENSE.txt"),
    (lambda p: make_archive(p, files={"README.txt": README, "LICENSE.txt": LICENSE}), "has no .sfz"),
    (lambda p: make_archive(p, files={"README.txt": README, "LICENSE.txt": LICENSE, SFZ_NAME: SFZ,
                                      "tool.sh": "echo hi\n"}), "unexpected file in the archive: tool.sh"),
    (lambda p: make_archive(p, sfz=SFZ.replace("samples/F#4.wav", "samples/missing.wav")), "no such sample"),
])
def test_a_wrong_archive_is_rejected_and_leaves_nothing_behind(tmp_path, dirs, monkeypatch, build, message):
    url, sha = build(tmp_path / "bad.7z")
    monkeypatch.setitem(CATALOG, "freepats-synth-choir",
                        Source(**{**CATALOG["freepats-synth-choir"].__dict__, "url": url, "sha256": sha}))
    with pytest.raises(SetupError, match=message):
        setup_voices("freepats-synth-choir")
    nothing_behind(dirs)


@needs_bsdtar
def test_a_registry_that_cannot_be_written_leaves_nothing_installed(source, dirs):
    voicepacks.default_path().parent.mkdir(parents=True)
    voicepacks.default_path().write_text("{not json")             # registering fails after the move into place
    with pytest.raises(voicepacks.PackError, match="cannot read"):
        setup_voices("freepats-synth-choir")
    assert not dirs.exists() or list(dirs.iterdir()) == []
    assert voicepacks.default_path().read_text() == "{not json"     # the user's file is left as it was


@pytest.mark.parametrize("entry", ["/etc/passwd", "../evil.txt", "top/../../evil.txt", "C:\\evil.txt",
                                   "a/b", "other top/x.txt"])
def test_unsafe_or_stray_archive_entries_are_refused_before_extraction(entry):
    with pytest.raises(SetupError, match="unsafe|outside"):
        voicesetup._check_entries(["top/", "top/a.wav", entry], "top")


def test_without_bsdtar_or_7z_setup_says_what_to_install(monkeypatch, dirs, capsys):
    monkeypatch.setattr(voicesetup.shutil, "which", lambda name: None)
    code, out, err = run(capsys, "setup-voices", "freepats-synth-choir")
    entry = CATALOG["freepats-synth-choir"]
    assert code == 1
    assert out == f"downloading {entry.name} ({entry.license}, {entry.attribution}) from {entry.url}\n\n"
    assert err == ("gentle-stream: setup-voices failed: extracting .7z needs bsdtar or 7z (macOS includes "
                        "bsdtar; on Linux install libarchive-tools or p7zip-full)\n")
    nothing_behind(dirs)


# ------------------------------------------------------------ the command
@needs_bsdtar
def test_cli_installs_then_reports_it_is_installed(source, capsys, dirs):
    code, out, err = run(capsys, "setup-voices", "freepats-synth-choir")
    assert (code, err) == (0, "")
    lines = out.strip().split("\n")
    assert lines[0] == f"downloading FreePats Synth Pad Choir (CC0-1.0, {source.attribution}) from {source.url}"
    assert lines[-1] == (f"installed {dirs / 'freepats-synth-choir'} (SHA-256 verified; license: "
                         f"{dirs / 'freepats-synth-choir' / 'LICENSES.txt'}); the choir now sings it")
    assert run(capsys, "setup-voices", "freepats-synth-choir") == (
        0, f"FreePats Synth Pad Choir already installed: {dirs / 'freepats-synth-choir'}; the choir sings it\n", "")
    assert "FreePats Synth Pad Choir · license: CC0-1.0" in run(capsys, "voices", "list")[1]


def test_cli_rejects_an_unknown_pack(capsys):
    with pytest.raises(SystemExit) as e:
        main(["setup-voices", "nope"])
    assert e.value.code == 2 and "invalid choice: 'nope'" in capsys.readouterr().err


def test_help_lists_setup_voices(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "setup-voices" in capsys.readouterr().out
