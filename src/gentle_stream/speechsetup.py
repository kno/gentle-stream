"""`gentle-stream setup-speech [VOICE]`: install a Piper voice for spoken phrases in one command.

Piper (`uv tool install piper-tts`, GPL-3.0) is a separate program, like espeak-ng: gentle-stream runs it, never
imports it. Its voices are ONNX models; only voices whose licence allows a broadcast are in `CATALOG`. Almost every
Spanish Piper voice was fine-tuned from the US English lessac voice, whose recordings are licensed for research only;
carlfm was trained from scratch on a public-domain dataset. Each file is pinned to a Hugging Face revision and a
SHA-256, downloaded with the `setup-samples` machinery into a private staging folder, and moved into place under
`$XDG_CACHE_HOME/gentle-stream/speech/VOICE/` with a `LICENSES.txt` only once every file was verified; on any
failure nothing is left behind.
"""
from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .samples import SetupError, _download, cache_dir

LICENSES_NAME = "LICENSES.txt"
PROGRAM = "piper"
INSTALL_PROGRAM = "the Piper program is not installed: uv tool install piper-tts (or pip install piper-tts)"
_REVISION = "5041a7a49ae5b3a0f30e6837769eb03fdbb231bd"
_BASE = f"https://huggingface.co/rhasspy/piper-voices/resolve/{_REVISION}/es/es_ES/carlfm/x_low/"


@dataclass(frozen=True)
class SpeechVoice:
    language: str                               # as `ctl say --list-voices` shows it
    model: str                                  # the .onnx file among `files`
    revision: str
    license: str
    source: str                                 # the dataset, for LICENSES.txt
    files: dict[str, tuple[str, str]]           # file name -> (URL, SHA-256)


CATALOG = {
    "carlfm": SpeechVoice(
        language="es_ES",
        model="es_ES-carlfm-x_low.onnx",
        revision=_REVISION,
        license="Public domain (dataset), trained from scratch",
        source="https://github.com/carlfm01/my-speech-datasets",
        files={
            "es_ES-carlfm-x_low.onnx": (
                _BASE + "es_ES-carlfm-x_low.onnx",
                "d69677323a907cd4963f42b29c20a98b5d6bfa7f3e64df339915e4650c00d125"),
            "es_ES-carlfm-x_low.onnx.json": (
                _BASE + "es_ES-carlfm-x_low.onnx.json",
                "d9bdfa9ff01eb2bc9e62e7d2593939d1e4c4d8eb7cf75f972731539d12399966"),
            "MODEL_CARD": (
                _BASE + "MODEL_CARD",
                "a6e62a3d36c37c7702d877f784001208b952e2bf4d17c72a6b5da442fbefb4b3"),
        },
    ),
}


def speech_dir() -> Path:
    return cache_dir() / "speech"


def installed() -> dict[str, Path]:
    """Each installed voice and its model: every pinned file and the LICENSES.txt are there."""
    found = {}
    for key, voice in CATALOG.items():
        folder = speech_dir() / key
        if all((folder / name).is_file() for name in (*voice.files, LICENSES_NAME)):
            found[key] = folder / voice.model
    return found


def program() -> str | None:
    """The Piper program's path, or None."""
    return shutil.which(PROGRAM)


def installed_message(key: str, folder: Path, already: bool) -> str:
    """What `setup-speech` (and the TUI's voices dialog) says once `key` is in `folder`; it names the missing
    program too, without which the voice is not used."""
    done = (f"{key} already installed: {folder}" if already
            else f"installed {folder} (SHA-256 verified; license: {folder / LICENSES_NAME})")
    done += "; phrases are spoken with it" if program() else f"; {INSTALL_PROGRAM}"
    return done


def _licenses(key: str, voice: SpeechVoice) -> str:
    lines = [f"Piper voice {key} ({voice.language}), used by gentle-stream to speak phrases.",
             f"License: {voice.license}.", f"Dataset: {voice.source}",
             f"Downloaded from rhasspy/piper-voices at revision {voice.revision}; SHA-256 of each file:"]
    lines += [f"  {name}  {sha}  {url}" for name, (url, sha) in voice.files.items()]
    return "\n".join(lines) + "\n"


def setup_speech(key: str, progress: Callable[[int, int | None], None] | None = None) -> Path:
    """Download and verify `key`'s files into its folder (nothing when already there); raises SetupError (a
    ChecksumError for a file that does not match) and then leaves nothing behind."""
    voice = CATALOG[key]
    folder = speech_dir() / key
    if key in installed():
        return folder
    speech_dir().mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=speech_dir(), prefix=".staging-"))
    temps: list[Path] = []
    try:
        for name, (url, sha) in voice.files.items():
            _download(url, sha, staging, temps, progress).replace(staging / name)
        (staging / LICENSES_NAME).write_text(_licenses(key, voice))
        shutil.rmtree(folder, ignore_errors=True)        # an earlier install that did not finish
        staging.replace(folder)
    except OSError as e:
        raise SetupError(f"cannot install {key}: {e}") from e
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return folder
