"""Shared test setup: no test reads or writes the user's real configuration (saved prompts, journeys, voice packs,
the stream key), and no test reaches the user's real background player.

Every test gets a private, empty XDG_CONFIG_HOME and XDG_RUNTIME_DIR (short, under /tmp, so a socket path fits); a test
that needs another one sets it itself (tests/test_daemon.py's `runtime` fixture does). The user's Piper voice is out of
sight too, so no test speaks with the real Piper; the cache stays shared (some tests use the real soundfont).
"""
import os
import shutil
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _private_config(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config")))


@pytest.fixture(autouse=True)
def _one_stereo_output(monkeypatch):
    """The player never sees this machine's real devices (their channels vary): one stereo output, the default."""
    from gentle_stream import outputs

    monkeypatch.setattr(outputs, "_query", lambda: (
        [{"name": "Test speakers", "max_output_channels": 2, "default_samplerate": 44100.0}], 0))


@pytest.fixture(autouse=True)
def _no_real_piper_voice(monkeypatch, tmp_path_factory):
    """An empty folder of Piper voices, unless the test sets its own XDG_CACHE_HOME; every Piper started is closed."""
    from gentle_stream import speech, speechsetup

    real, empty, original = os.environ.get("XDG_CACHE_HOME"), tmp_path_factory.mktemp("speech"), speechsetup.speech_dir
    monkeypatch.setattr(speechsetup, "speech_dir",
                        lambda: empty if os.environ.get("XDG_CACHE_HOME") == real else original())
    yield
    speech.close_piper()


@pytest.fixture(autouse=True)
def _private_runtime(monkeypatch):
    """A `ctl` command in a test must find no player rather than the one the user is listening to."""
    root = tempfile.mkdtemp(prefix="gs-", dir="/tmp")
    monkeypatch.setenv("XDG_RUNTIME_DIR", root)
    yield
    shutil.rmtree(root, ignore_errors=True)
