"""Shared test setup: no test reads or writes the user's real configuration (saved prompts, journeys, voice packs).

Every test gets a private, empty XDG_CONFIG_HOME; a test that needs another one (or none) sets it itself.
"""
import pytest


@pytest.fixture(autouse=True)
def _private_config(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config")))
