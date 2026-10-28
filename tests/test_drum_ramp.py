"""PM-019: drums step up and down with the journey, one level per 4-bar phrase."""
import pytest

from gentle_stream.engine import Engine
from gentle_stream.journey import BUILTIN, Journey, drums_for_energy
from gentle_stream.style import DRUMS, Style

RAMP = {"version": 1, "name": "ramp", "drums": "energy", "stages": [
    {"name": "Rise", "seconds": 120, "to": {"energy": 1.0, "bpm": 90}},
]}
EXPLICIT = {"version": 1, "name": "jump", "stages": [
    {"name": "Quiet", "seconds": 20, "to": {"bpm": 90}, "drums": "none"},
    {"name": "Loud", "seconds": 90, "drums": "busy"},
]}


def drums_per_bar(data, bars, style=None):
    e = Engine(style or Style(energy=0.0, drums="soft", bpm=90), seed=5, samples=False)
    e.queue_journey(Journey.from_dict(data))
    out = []
    for _ in range(bars):
        e.render_bar()
        out.append((e.bar - 1, e.style.drums, e.piece))
    return out


def assert_ramps_one_level_per_phrase(rows):
    for (_, before, piece), (next_bar, after, next_piece) in zip(rows, rows[1:], strict=False):
        if before != after and piece == next_piece:
            assert next_bar % 4 == 0, (next_bar, before, after)
            assert abs(DRUMS.index(after) - DRUMS.index(before)) == 1, (next_bar, before, after)


# ------------------------------------------------------------ the journey file
@pytest.mark.parametrize("energy, level", [(0.0, "none"), (0.24, "none"), (0.25, "soft"), (0.49, "soft"),
                                           (0.5, "lofi"), (0.74, "lofi"), (0.75, "busy"), (1.0, "busy")])
def test_energy_maps_to_a_drum_level(energy, level):
    assert drums_for_energy(energy) == level


def test_drum_settings_are_parsed_held_and_written_back():
    ramp, explicit = Journey.from_dict(RAMP), Journey.from_dict(EXPLICIT)
    assert ramp.drums == "energy" and ramp.to_dict()["drums"] == "energy"
    assert [s.drums for s in explicit.stages] == ["none", "busy"]
    assert explicit.drums_at(10, energy=0.9) == "none"           # an explicit level wins over energy
    assert explicit.drums_at(50, energy=0.0) == "busy"
    assert ramp.drums_at(0, energy=0.6) == "lofi"
    assert Journey.from_dict(explicit.to_dict()) == explicit
    assert Journey.from_dict(ramp.to_dict()) == ramp


def test_a_journey_without_drum_settings_does_not_drive_drums():
    journey = BUILTIN["wind-down"]
    assert not journey.drives_drums and journey.drums_at(0, energy=1.0) is None
    assert "drums" not in journey.to_dict() and all("drums" not in s for s in journey.to_dict()["stages"])


@pytest.mark.parametrize("data, message", [
    ({"version": 1, "drums": "loud", "stages": [{"seconds": 10}]}, '"drums" must be "energy"'),
    ({"version": 1, "stages": [{"seconds": 10, "drums": "jazz"}]},
     'stage 1: "drums" must be one of none, soft, lofi, busy'),
    ({"version": 1, "stages": [{"seconds": 10, "drums": 2}]}, 'stage 1: "drums" must be one of none, soft, lofi, busy'),
], ids=["journey", "stage-name", "stage-number"])
def test_bad_drum_settings_are_rejected(data, message):
    with pytest.raises(ValueError, match=message):
        Journey.from_dict(data, name="bad")


# ------------------------------------------------------------ acceptance criteria
def test_an_energy_ramp_steps_the_drums_up_on_phrase_boundaries_one_level_at_a_time():
    rows = drums_per_bar(RAMP, 48)
    assert rows[0][1] == "none"                                  # energy 0: no drums from the first phrase
    assert rows[-1][1] == "busy"
    assert_ramps_one_level_per_phrase(rows)
    assert [level for level in DRUMS if any(r[1] == level for r in rows)] == list(DRUMS)   # never skips one


def test_an_explicit_jump_still_climbs_one_level_per_phrase():
    rows = drums_per_bar(EXPLICIT, 30, style=Style(energy=0.5, drums="lofi", bpm=90))
    assert_ramps_one_level_per_phrase(rows)
    seen = [r[1] for r in rows]
    assert "none" in seen and seen[-1] == "busy"
    first_busy = seen.index("busy")
    assert "soft" in seen[:first_busy] and "lofi" in seen[seen.index("none"):first_busy]


def test_drums_change_only_on_phrase_boundaries_while_energy_moves_both_ways():
    data = {"version": 1, "name": "wave", "drums": "energy", "stages": [
        {"name": "Up", "seconds": 40, "to": {"energy": 1.0, "bpm": 90}},
        {"name": "Down", "seconds": 40, "to": {"energy": 0.0}},
    ]}
    rows = drums_per_bar(data, 40)
    assert_ramps_one_level_per_phrase(rows)
    levels = [DRUMS.index(r[1]) for r in rows]
    assert max(levels) > levels[-1]                              # it came back down


def test_a_journey_without_drum_settings_leaves_the_style_drums():
    rows = drums_per_bar({"version": 1, "name": "plain", "stages": [{"seconds": 60, "to": {"energy": 1.0}}]}, 16)
    assert {r[1] for r in rows} == {"soft"}


def test_warm_up_ramps_its_drums_with_energy():
    journey = BUILTIN["warm-up"]
    assert journey.drums == "energy" and journey.drives_drums


def test_the_journey_prompt_offers_the_drum_settings(tmp_path):
    import json
    import stat
    import textwrap

    from gentle_stream.bridge import GentleShell

    log = tmp_path / "argv.json"
    script = tmp_path / "gentle-shell"
    script.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env python3
        import json, sys
        json.dump(sys.argv[1:], open({str(log)!r}, "w"))
        print({json.dumps(json.dumps(RAMP))})
        """))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    journey, _ = GentleShell(binary=str(script)).journey_from_prompt("build up")
    prompt = json.loads(log.read_text())[-1]
    assert '"drums": "energy"' in prompt and "none, soft, lofi, busy" in prompt
    assert journey.drums == "energy"
