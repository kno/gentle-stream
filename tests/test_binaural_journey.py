"""PM-015: a journey can move the binaural layer stage by stage."""
import math

import numpy as np
import pytest

from gentle_stream.binaural import Binaural
from gentle_stream.engine import SR, Engine, JourneyDriven
from gentle_stream.journey import BUILTIN, Journey, JourneySnapshot
from gentle_stream.style import Style

FLOAT32 = 1e-6

BINAURAL = {"version": 1, "name": "focus", "stages": [
    {"name": "Settle", "seconds": 30, "to": {"bpm": 70}, "binaural": {"carrier": 200, "beat": 6, "level": 0.05}},
    {"name": "Lift", "seconds": 30, "to": {"bpm": 90}, "binaural": {"carrier": 400, "beat": 10}},
    {"name": "Hold", "seconds": 30, "to": {"bpm": 90}},
]}


def without_binaural(data):
    """The same journey with every stage's binaural block removed: the music is identical."""
    return {**data, "stages": [{k: v for k, v in stage.items() if k != "binaural"} for stage in data["stages"]]}


def journey_layer(data, seconds, binaural=None):
    """The binaural layer alone while `data` plays: an engine running the journey minus the same engine running it
    without binaural blocks (the layer is added after the master chain, so the difference is exactly the layer)."""
    with_layer = Engine(Style(), seed=7, samples=False)
    without = Engine(Style(), seed=7, samples=False)
    for engine in (with_layer, without):
        if binaural is not None:
            engine.queue_binaural(binaural)
    with_layer.queue_journey(Journey.from_dict(data))
    without.queue_journey(Journey.from_dict(without_binaural(data)))
    bars = []
    while sum(len(b) for b in bars) < seconds * SR:
        bars.append(with_layer.render_bar().astype(np.float64) - without.render_bar().astype(np.float64))
    return np.concatenate(bars), with_layer


def dominant(x, start_seconds, window_seconds=0.25):
    """(left, right) dominant frequency and the bin width of a `window_seconds` FFT starting at `start_seconds`."""
    a = int(start_seconds * SR)
    segment = x[a: a + int(window_seconds * SR)]
    freqs = np.fft.rfftfreq(len(segment), 1 / SR)
    peaks = tuple(freqs[np.argmax(np.abs(np.fft.rfft(segment[:, c])))] for c in (0, 1))
    return peaks, freqs[1]


# ------------------------------------------------------------ the journey file
def test_a_stage_binaural_block_is_parsed_and_written_back():
    journey = Journey.from_dict(BINAURAL)
    assert journey.stages[0].binaural == {"carrier": 200.0, "beat": 6.0, "level": 0.05}
    assert journey.stages[1].binaural == {"carrier": 400.0, "beat": 10.0}
    assert journey.stages[2].binaural == {}
    assert journey.owns_binaural
    data = journey.to_dict()
    assert data["stages"][0]["binaural"] == {"carrier": 200.0, "beat": 6.0, "level": 0.05}
    assert "binaural" not in data["stages"][2]
    assert Journey.from_dict(data) == journey


def test_a_journey_without_binaural_blocks_is_written_exactly_as_before():
    journey = BUILTIN["warm-up"]
    assert not journey.owns_binaural
    assert all("binaural" not in stage for stage in journey.to_dict()["stages"])


def test_out_of_range_binaural_values_are_clamped_with_warnings():
    warnings = []
    data = {"version": 1, "stages": [{"seconds": 10, "binaural": {"carrier": 5000, "beat": 0.1, "level": 0.5}}]}
    journey = Journey.from_dict(data, warnings, name="loud")
    assert journey.stages[0].binaural == {"carrier": 1000.0, "beat": 0.5, "level": 0.08}
    assert warnings == ['stage 1: "binaural.carrier" clamped from 5000 to 1000.0',
                        'stage 1: "binaural.beat" clamped from 0.1 to 0.5',
                        'stage 1: "binaural.level" clamped from 0.5 to 0.08']


@pytest.mark.parametrize("block, message", [
    ("loud", 'stage 1: "binaural" must be an object'),
    ({"level": "high"}, 'stage 1: "binaural.level" must be a number'),
    ({"level": math.nan}, 'stage 1: "binaural.level" must be a number'),
    ({"level": True}, 'stage 1: "binaural.level" must be a number'),
], ids=["not-an-object", "not-a-number", "nan", "boolean"])
def test_a_malformed_binaural_block_is_rejected(block, message):
    with pytest.raises(ValueError, match=message):
        Journey.from_dict({"version": 1, "stages": [{"seconds": 10, "binaural": block}]}, name="bad")


def test_unknown_binaural_keys_are_ignored_like_unknown_fields():
    data = {"version": 1, "stages": [{"seconds": 10, "binaural": {"level": 0.05, "pattern": "pulse"}}]}
    assert Journey.from_dict(data, name="x").stages[0].binaural == {"level": 0.05}


# ------------------------------------------------------------ acceptance criteria
def test_the_rendered_frequencies_follow_the_journey_at_stage_midpoints():
    x, _ = journey_layer(BINAURAL, 48.0)
    for midpoint, (carrier, beat) in ((15.0, (200.0, 6.0)), (45.0, (300.0, 8.0))):
        (left, right), bin_width = dominant(x, midpoint - 0.125)
        assert abs(left - (carrier - beat / 2)) <= bin_width
        assert abs(right - (carrier + beat / 2)) <= bin_width


def test_the_journey_starts_the_layer_from_silence_and_keeps_its_phase_continuous():
    x, _ = journey_layer(BINAURAL, 40.0)
    assert x[0, 0] == 0.0 and np.abs(x[: SR // 100]).max() < 0.001
    top = Binaural(400, 10, 0.05)
    assert np.abs(np.diff(x, axis=0)).max() <= top.level * 2 * math.sin(math.pi * 405 / SR) + FLOAT32


def test_a_journey_without_binaural_leaves_the_layer_untouched():
    e = Engine(Style(), seed=7, samples=False)
    e.queue_binaural(Binaural(300, 8, 0.04))
    e.queue_journey(BUILTIN["warm-up"])
    for _ in range(3):
        e.render_bar()
    assert e.binaural == Binaural(300, 8, 0.04)
    e.queue_binaural(Binaural(250, 5, 0.03))                  # still yours to change
    e.render_bar()
    assert e.binaural == Binaural(250, 5, 0.03)


def test_a_journey_with_binaural_starts_from_the_layer_that_plays():
    x, e = journey_layer(BINAURAL, 4.0, binaural=Binaural(300, 8, 0.04))
    (left, right), bin_width = dominant(x, 0.0)
    assert abs(left - 296.0) <= bin_width + 1 and abs(right - 304.0) <= bin_width + 1   # gliding away from 300/8
    assert e.binaural is not None


def test_the_journey_drives_the_layer_and_refuses_a_manual_change_until_it_stops():
    e = Engine(Style(), seed=7, samples=False)
    e.queue_journey(Journey.from_dict(BINAURAL))
    with pytest.raises(JourneyDriven, match='binaural is driven by the journey "focus"; stop it first'):
        e.queue_binaural(Binaural())
    e.render_bar()
    with pytest.raises(JourneyDriven):
        e.queue_binaural(None)
    e.stop_journey()
    e.queue_binaural(None)                                    # the journey has let go of it
    e.render_bar()
    assert e.binaural is None


def test_stopping_the_journey_leaves_the_layer_where_it_was():
    e = Engine(Style(), seed=7, samples=False)
    e.queue_journey(Journey.from_dict(BINAURAL))
    for _ in range(3):
        e.render_bar()
    heading = e.binaural
    assert heading is not None and heading.carrier == 200.0 and heading.level > 0
    e.stop_journey()
    for _ in range(2):
        e.render_bar()
    assert e.binaural == heading


def test_the_snapshot_reports_the_binaural_values_and_none_without_them():
    e = Engine(Style(), seed=7, samples=False)
    e.queue_journey(Journey.from_dict(BINAURAL))
    e.render_bar()
    e.render_bar()
    snap = e.journey_snapshot
    assert snap is not None and snap.binaural is not None
    assert snap.binaural["carrier"] == 200.0 and snap.binaural["beat"] == 6.0 and 0 < snap.binaural["level"] <= 0.05
    plain = Engine(Style(), seed=7, samples=False)
    plain.queue_journey(BUILTIN["warm-up"])
    plain.render_bar()
    assert plain.journey_snapshot is not None and plain.journey_snapshot.binaural is None


def test_a_snapshot_from_an_older_player_has_no_binaural():
    old = {"name": "warm-up", "title": "Warm-up", "stage": 1, "stages": 4, "stage_name": "Settle",
           "progress": 0.5, "bpm": 60.0, "target_bpm": 60.0, "seconds_left": 570.0}
    snap = JourneySnapshot.from_dict(old)
    assert snap is not None and snap.binaural is None


def test_the_daemon_refuses_a_manual_binaural_change_while_the_journey_drives_it():
    from gentle_stream.daemon import handle
    from tests.test_daemon import fake_player

    player = fake_player()
    player.engine.queue_journey(Journey.from_dict(BINAURAL))
    assert handle(player, {"cmd": "binaural", "on": True}) == {
        "ok": False, "error": 'binaural is driven by the journey "focus"; stop it first (gentle-stream journey stop)'}


# ------------------------------------------------------------ the built-in and the model prompt
def test_ambient_to_synthwave_fades_its_binaural_texture_out_before_the_synthwave_stage():
    journey = BUILTIN["ambient-to-synthwave"]
    assert journey.owns_binaural
    named = [(stage.name, dict(stage.binaural)) for stage in journey.stages if stage.binaural]
    assert named == [("Dawn", {"carrier": 200.0, "beat": 6.0, "level": 0.05}), ("Lift", {"level": 0.0})]
    lift = [stage.name for stage in journey.stages].index("Lift")
    assert all(stage.genre != "synthwave" for stage in journey.stages[: lift + 1])


def test_the_journey_prompt_offers_the_optional_binaural_block_without_health_claims(tmp_path):
    import json
    import os
    import stat
    import textwrap

    from gentle_stream.bridge import GentleShell
    from tests.test_bridge import USAGE, jsonl, text  # noqa: F401

    log = tmp_path / "argv.json"
    script = tmp_path / "gentle-shell"
    script.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env python3
        import json, sys
        json.dump(sys.argv[1:], open({str(log)!r}, "w"))
        print({json.dumps(json.dumps(BINAURAL))})
        """))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    journey, _ = GentleShell(binary=str(script)).journey_from_prompt("focus")
    prompt = json.loads(log.read_text())[-1]
    assert '"binaural"' in prompt and "carrier 40-1000" in prompt and "level 0-0.08" in prompt
    assert "never claim any effect" in prompt
    assert journey.owns_binaural
    assert os.path.exists(log)
