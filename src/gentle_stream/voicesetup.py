"""`gentle-stream setup-voices NAME`: install a redistributable voice pack in one command (PM-030).

Only packs whose license was verified by inspecting the archive are in `CATALOG`, each pinned to a URL and a
SHA-256. Installing reuses the `setup-samples` machinery: the download is verified before anything is extracted, and
on any failure nothing is left behind. The archive is untrusted data: its listing is checked first (one top folder,
relative paths, only SFZ, WAV and text files), it is extracted into a private staging folder by a system tool
(`bsdtar`, or `7z`; Python cannot read 7z on its own), nothing in it is ever run, and the SFZ must load as a voice
pack before the folder is moved into place. The pack is installed under `$XDG_CACHE_HOME/gentle-stream/voices/`
with a `pack.json` and a `LICENSES.txt`, then registered and made the choir's voice, as `voices add` does.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from .samples import SetupError, _download, cache_dir
from .voicepacks import PackError, VoiceStore, load_pack

ALLOWED = (".sfz", ".wav", ".txt")
LICENSES_NAME = "LICENSES.txt"
NEEDS_TOOL = ("extracting .7z needs bsdtar or 7z (macOS includes bsdtar; on Linux install libarchive-tools or "
              "p7zip-full)")


@dataclass(frozen=True)
class Source:
    name: str             # the pack name shown by `voices list`
    url: str
    sha256: str
    license: str
    attribution: str
    note: str             # one line for LICENSES.txt: what the pack is


CATALOG = {
    "freepats-synth-choir": Source(
        name="FreePats Synth Pad Choir",
        url=("https://github.com/freepats/synth-pad-choir/releases/download/2020-05-16/"
             "SynthPadChoir-SFZ+WAV-20200516.7z"),
        sha256="19f94afc8aed5e120b444da668a51a1737a1e87b772ae93b495d0fc42ff92a16",
        license="CC0-1.0",
        attribution="快乐爱的小精灵 (Elf of Happy and Love), FreePats project",
        note=("General MIDI #92, Synth Pad 4 (choir), version 2020-05-16: a synthetic choir made with the ZynAddSubFX "
              "synthesizer, not recorded human voices"),
    ),
}


def voices_dir() -> Path:
    return cache_dir() / "voices"


def installed(key: str) -> Path | None:
    """The folder of an installed pack, or None; LICENSES.txt is written last, so it marks a complete install."""
    folder = voices_dir() / key
    return folder if (folder / LICENSES_NAME).is_file() else None


def _tool() -> tuple[str, str]:
    for name, kind in (("bsdtar", "bsdtar"), ("7z", "7z"), ("7zz", "7z"), ("7za", "7z")):
        path = shutil.which(name)
        if path:
            return path, kind
    raise SetupError(NEEDS_TOOL)


def _list(tool: tuple[str, str], archive: Path) -> list[str]:
    path, kind = tool
    cmd = [path, "-tf", str(archive)] if kind == "bsdtar" else [path, "l", "-ba", "-slt", str(archive)]
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SetupError(f"cannot list the archive: {done.stderr.strip() or done.returncode}")
    if kind == "bsdtar":
        return [line for line in done.stdout.split("\n") if line]
    return [line[len("Path = "):] for line in done.stdout.split("\n") if line.startswith("Path = ")]


def _extract(tool: tuple[str, str], archive: Path, into: Path) -> None:
    path, kind = tool
    cmd = [path, "-xf", str(archive), "-C", str(into)] if kind == "bsdtar" else [path, "x", "-y", f"-o{into}",
                                                                                 str(archive)]
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SetupError(f"cannot extract the archive: {done.stderr.strip() or done.returncode}")


def _check_entries(entries: list[str], top: str | None = None) -> str:
    """The archive's single top folder, after refusing absolute paths, `..`, stray top-level entries and anything
    but SFZ, WAV and text files."""
    names = []
    for entry in entries:
        name = entry.replace("\\", "/")
        parts = PurePosixPath(name).parts
        if (not parts or name.startswith("/") or PureWindowsPath(entry).drive or ".." in parts
                or any(":" in p for p in parts)):
            raise SetupError(f"unsafe path in the archive: {entry}")
        names.append((name, parts))
    tops = {parts[0] for _, parts in names}
    expected = top if top is not None else (next(iter(tops)) if len(tops) == 1 else None)
    if expected is None or tops != {expected}:
        raise SetupError(f"files outside the archive's top folder: {', '.join(sorted(tops - {expected}))}")
    for name, parts in names:
        is_dir = name.endswith("/") or len(parts) == 1
        if not is_dir and PurePosixPath(name).suffix.lower() not in ALLOWED:
            raise SetupError(f"unexpected file in the archive: {PurePosixPath(name).name}")
    return expected


def _licenses(source: Source, folder: Path) -> str:
    def member(name: str) -> str:
        path = folder / name
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else "(not in the archive)"

    return f"""{source.name} — third-party sound asset used by gentle-stream (not distributed with it)

Asset:      {source.note}
Source:     {source.url}
SHA-256:    {source.sha256} (archive as downloaded)
Credit:     {source.attribution}
License:    {source.license} (the archive's LICENSE.txt and README.txt are reproduced in full below)

---------------------------------------------------------------------------------------------------- LICENSE.txt
{member("LICENSE.txt")}
----------------------------------------------------------------------------------------------------- README.txt
{member("README.txt")}"""


def setup_voices(key: str, progress: Callable[[int, int | None], None] | None = None) -> Path:
    """Install the catalog pack `key` (download, verify, check, extract, describe) and make it the choir's voice;
    an installed pack is only registered again. On any failure nothing is left behind and nothing is registered."""
    source = CATALOG[key]
    if (done := installed(key)) is not None:
        VoiceStore().add(done)
        return done
    root = voices_dir()
    created = not root.exists()
    root.mkdir(parents=True, exist_ok=True)
    temps: list[Path] = []
    staging = Path(tempfile.mkdtemp(dir=root, prefix=".partial-"))
    final = root / key
    moved = False
    try:
        tool = _tool()
        archive = _download(source.url, source.sha256, root, temps, progress)
        top = _check_entries(_list(tool, archive))
        out = staging / "x"
        out.mkdir()
        _extract(tool, archive, out)
        for path in out.rglob("*"):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise SetupError(f"unexpected entry in the archive: {path.name}")
        folder = out / top
        if not (folder / "LICENSE.txt").is_file():
            raise SetupError("the archive has no LICENSE.txt")
        sfz = sorted(folder.glob("*.sfz"))
        if len(sfz) != 1:
            raise SetupError("the archive has no .sfz instrument" if not sfz else "the archive has several .sfz")
        (folder / "pack.json").write_text(json.dumps({
            "name": source.name, "license": source.license, "source": source.url, "attribution": source.attribution,
            "redistributable": True, "sfz": sfz[0].name}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            load_pack(folder)                        # the SFZ and its samples must load before anything is installed
        except PackError as e:
            raise SetupError(str(e)) from e
        (folder / LICENSES_NAME).write_text(_licenses(source, folder), encoding="utf-8")
        os.replace(folder, final)
        moved = True
        VoiceStore().add(final)
        return final
    except BaseException:
        if moved:                                    # in place but not registered: take it back out
            shutil.rmtree(final, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        for p in temps:
            p.unlink(missing_ok=True)
        if created and root.exists() and not any(root.iterdir()):
            root.rmdir()
