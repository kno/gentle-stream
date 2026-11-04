"""Local, bounded journey preference signals."""
import json
import subprocess
import sys

import pytest

from gentle_stream.journey_preferences import PreferenceError, PreferenceStore


def test_saves_outweigh_a_single_skip_and_survive_reload(tmp_path):
    path = tmp_path / "preferences.json"
    prefs = PreferenceStore(path)
    prefs.saved(["ballad", "lofi"])
    prefs.skipped("ballad")
    assert PreferenceStore(path).scores() == {"ballad": 3, "lofi": 4}


def test_clear_removes_learned_signals(tmp_path):
    prefs = PreferenceStore(tmp_path / "preferences.json")
    prefs.saved(["ballad"])
    prefs.clear()
    assert prefs.scores() == {}


def test_invalid_file_is_not_overwritten(tmp_path):
    path = tmp_path / "preferences.json"
    original = b"not json"
    path.write_bytes(original)
    prefs = PreferenceStore(path)
    with pytest.raises(PreferenceError):
        prefs.saved(["ballad"])
    assert path.read_bytes() == original


@pytest.mark.parametrize("data", [{"version": 2, "scores": {}}, {"version": 1, "scores": {"ballad": True}},
                                  {"version": 1, "scores": {"ballad": 101}}, {"version": 1, "scores": []}])
def test_invalid_structures_are_not_overwritten(tmp_path, data):
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps(data))
    original = path.read_bytes()
    with pytest.raises(PreferenceError):
        PreferenceStore(path).saved(["ballad"])
    assert path.read_bytes() == original


def test_parallel_process_updates_are_not_lost(tmp_path):
    path = tmp_path / "preferences.json"
    script = ("from gentle_stream.journey_preferences import PreferenceStore; "
              f"p=PreferenceStore({str(path)!r}); "
              "[p.skipped('ballad') for _ in range(8)]")
    processes = [subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for _ in range(4)]
    for process in processes:
        out, err = process.communicate(timeout=20)
        assert (process.returncode, out, err) == (0, b"", b"")
    assert PreferenceStore(path).scores() == {"ballad": -32}


def test_only_known_genres_are_recorded_and_counts_are_bounded(tmp_path):
    path = tmp_path / "preferences.json"
    prefs = PreferenceStore(path)
    for _ in range(110):
        prefs.skipped("ballad")
    prefs.saved(["not-a-genre"])
    assert prefs.scores() == {"ballad": -100}
    assert json.loads(path.read_text())["version"] == 1
    for _ in range(60):
        prefs.saved(["lofi"])
    assert prefs.scores()["lofi"] == 100
