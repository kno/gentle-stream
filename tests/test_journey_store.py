import json

import pytest

from gentle_stream.journey import Journey, JourneyStore, JourneyStoreError, Stage, default_store_path
from gentle_stream.presets import NAME_MAX

RISE = Journey("rise", (Stage("Start", 60, {"bpm": 70.0}), Stage("Peak", 120, {"bpm": 110.0, "energy": 0.8})),
               description="70 to 110 bpm", title="Rise")


def stored(store, name) -> Journey:
    journey = store.get(name)
    assert journey is not None
    return journey


@pytest.fixture
def path(tmp_path):
    return tmp_path / "config" / "gentle-stream" / "journeys.json"


def test_the_default_path_follows_xdg_config_home_next_to_the_presets(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_store_path() == tmp_path / "gentle-stream" / "journeys.json"
    assert JourneyStore().path == default_store_path()
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert default_store_path().parts[-3:] == (".config", "gentle-stream", "journeys.json")


def test_a_missing_file_is_an_empty_store(path):
    store = JourneyStore(path)
    assert store.list() == []
    assert store.error is None
    assert not path.exists()


def test_save_get_list_and_delete(path):
    store = JourneyStore(path)
    assert store.save("Morning run", RISE) == ("Morning run", False)
    saved = stored(store, "MORNING RUN")
    assert (saved.name, saved.title) == ("Morning run", "Morning run")   # shown as the person called it
    assert (saved.stages, saved.end, saved.description) == (RISE.stages, RISE.end, RISE.description)
    store.save("blue hour", RISE)
    store.save("Archive", RISE)
    assert [name for name, _ in store.list()] == ["Archive", "blue hour", "Morning run"]
    assert store.get("nope") is None
    assert store.delete("BLUE HOUR")
    assert not store.delete("blue hour")
    assert [name for name, _ in store.list()] == ["Archive", "Morning run"]


def test_saving_the_same_name_ignoring_case_replaces_it(path):
    store = JourneyStore(path)
    store.save("Morning Run", RISE)
    other = Journey("other", (Stage("Only", 30, {"energy": 0.2}),))
    assert store.save("  morning   run ", other) == ("morning run", True)
    assert [name for name, _ in store.list()] == ["morning run"]
    assert stored(store, "MORNING RUN").stages == other.stages


def test_journeys_persist_across_store_instances(path):
    JourneyStore(path).save("Morning run", RISE)
    assert stored(JourneyStore(path), "morning run").stages == RISE.stages


def test_the_file_is_written_atomically_as_readable_versioned_json(path):
    JourneyStore(path).save("Morning run", RISE)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    (entry,) = data["journeys"]
    assert entry["name"] == "Morning run"
    assert entry["journey"]["stages"][1] == {"name": "Peak", "seconds": 120.0, "to": {"bpm": 110.0, "energy": 0.8}}
    assert isinstance(entry["saved_at"], str) and entry["saved_at"]
    assert [p.name for p in path.parent.iterdir()] == ["journeys.json"]   # no temp file left behind


def test_saving_or_deleting_another_journey_keeps_each_saved_at(path):
    store = JourneyStore(path)
    store.save("one", RISE)
    first = json.loads(path.read_text(encoding="utf-8"))["journeys"][0]["saved_at"]
    store.save("two", RISE)
    store.delete("two")
    assert json.loads(path.read_text(encoding="utf-8"))["journeys"][0]["saved_at"] == first


def test_a_corrupt_file_does_not_crash_and_is_left_untouched(path):
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    store = JourneyStore(path)
    assert store.list() == []
    assert store.error is not None and "journeys.json" in store.error
    with pytest.raises(JourneyStoreError):
        store.save("Morning run", RISE)
    with pytest.raises(JourneyStoreError):
        store.delete("Morning run")
    assert path.read_text(encoding="utf-8") == "{not json"


@pytest.mark.parametrize("content", ["[1, 2]", '{"version": 2, "journeys": []}', '{"version": 1}'])
def test_a_file_with_the_wrong_shape_is_reported_as_corrupt_and_kept(path, content):
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    store = JourneyStore(path)
    assert store.list() == []
    assert store.error
    with pytest.raises(JourneyStoreError):
        store.save("Morning run", RISE)
    assert path.read_text(encoding="utf-8") == content


def test_invalid_entries_are_skipped_and_reported(path):
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "journeys": [
        "junk",
        {"name": "", "journey": RISE.to_dict()},
        {"name": "no journey"},
        {"name": "bad stages", "journey": {"version": 1, "stages": []}},
        {"name": "Kept", "journey": RISE.to_dict(), "saved_at": "2026-10-27T10:00:00+00:00"},
    ]}), encoding="utf-8")
    store = JourneyStore(path)
    assert [name for name, _ in store.list()] == ["Kept"]
    assert store.error is not None and "4" in store.error


@pytest.mark.parametrize("raw, expected", [("  Morning   run ", "Morning run"), ("x" * NAME_MAX, "x" * NAME_MAX)])
def test_names_are_trimmed(path, raw, expected):
    assert JourneyStore(path).save(raw, RISE) == (expected, False)


@pytest.mark.parametrize("raw", ["", "   ", "x" * (NAME_MAX + 1)])
def test_invalid_names_are_rejected(path, raw):
    with pytest.raises(JourneyStoreError):
        JourneyStore(path).save(raw, RISE)
    assert not path.exists()


@pytest.mark.parametrize("raw", ["warm-up", " WARM-UP ", "Wind-Down"])
def test_built_in_names_cannot_be_overwritten(path, raw):
    store = JourneyStore(path)
    store.save("Morning run", RISE)
    before = path.read_bytes()
    with pytest.raises(JourneyStoreError, match="built-in journey"):
        store.save(raw, RISE)
    assert path.read_bytes() == before
