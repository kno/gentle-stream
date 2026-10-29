"""Shared test setup: no test reads or writes the user's real configuration (saved prompts, journeys, voice packs,
the stream key), and no test reaches the user's real background player.

Every test gets a private, empty XDG_CONFIG_HOME and XDG_RUNTIME_DIR (short, under /tmp, so a socket path fits); a test
that needs another one sets it itself (tests/test_daemon.py's `runtime` fixture does).
"""
import shutil
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _private_config(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config")))


@pytest.fixture(autouse=True)
def _private_runtime(monkeypatch):
    """A `ctl` command in a test must find no player rather than the one the user is listening to."""
    root = tempfile.mkdtemp(prefix="gs-", dir="/tmp")
    monkeypatch.setenv("XDG_RUNTIME_DIR", root)
    yield
    shutil.rmtree(root, ignore_errors=True)
