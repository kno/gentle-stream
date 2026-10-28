"""PM-018: stages decide which layers play; changes land on 4-bar phrase boundaries."""
import pytest

from gentle_stream.engine import Engine
from gentle_stream.journey import BUILTIN, LAYERS, Journey, Stage
from gentle_stream.style import Style

STYLE = Style(bpm=70, drums="soft", lead="nylon", energy=0.9, lead_density=0.9)
DATA = {"version": 1, "name": "build", "stages": [
    {"name": "Bare", "seconds": 30, "to": {"bpm": 70}, "layers": {"drums": False, "lead": False}},
    {"name": "Beat", "seconds": 30, "layers": {"drums": True}},
    {"name": "Full", "seconds": 60, "layers": {"lead": True}},
]}


def render(journey, bars, style=STYLE, stop_at=None):
    """(bar, journey seconds at its start, planned layers, section) of each rendered bar."""
    e = Engine(style, seed=3, samples=False)
    e.queue_journey(journey)
    out, t = [], 0.0
    for bar in range(bars):
        if stop_at is not None and bar == stop_at:
            e.stop_journey()
        e.render_bar()
        out.append((e.bar - 1, t, e.layers, e.section))
        t += e.bar_seconds
    return out


def expected_mask(journey, rows, stop_at=None):
    """The masked layers in force at each row: the stage's mask, switched only on a bar where bar % 4 == 0."""
    active, masks = frozenset(), []
    for i, (bar, t, _, _) in enumerate(rows):
        target = journey.masked_layers(t) if stop_at is None or i < stop_at else frozenset()
        if bar % 4 == 0:
            active = target
        masks.append(active)
    return masks


# ------------------------------------------------------------ the journey file
def test_stage_layers_are_parsed_held_and_written_back():
    journey = Journey.from_dict(DATA)
    assert [dict(s.layers) for s in journey.stages] == [{"drums": False, "lead": False}, {"drums": True},
                                                      {"lead": True}]
    assert journey.masked_layers(10) == {"drums", "lead"}
    assert journey.masked_layers(40) == {"lead"}                  # drums back, lead still held off
    assert journey.masked_layers(70) == frozenset()
    assert journey.to_dict()["stages"][1]["layers"] == {"drums": True}
    assert Journey.from_dict(journey.to_dict()) == journey


def test_a_journey_without_layers_masks_nothing_and_is_written_as_before():
    journey = BUILTIN["warm-up"]
    assert journey.masked_layers(0) == frozenset() and journey.masked_layers(10_000) == frozenset()
    assert all("layers" not in stage for stage in journey.to_dict()["stages"])


@pytest.mark.parametrize("layers, message", [
    ("drums", 'stage 1: "layers" must be an object'),
    ({"drum": False}, 'stage 1: unknown layer "drum" \\(choose from chords, bass, drums, lead, counter\\)'),
    ({"drums": "no"}, 'stage 1: "layers.drums" must be true or false'),
    ({"drums": 0}, 'stage 1: "layers.drums" must be true or false'),
], ids=["not-an-object", "unknown", "not-a-boolean", "number"])
def test_malformed_layers_are_rejected(layers, message):
    with pytest.raises(ValueError, match=message):
        Journey.from_dict({"version": 1, "stages": [{"seconds": 10, "layers": layers}]}, name="bad")


def test_the_layer_names_are_the_shared_bar_plan_layers():
    assert LAYERS == ("chords", "bass", "drums", "lead", "counter")
    with pytest.raises(ValueError):
        Stage("x", 10, {}, layers={"vocals": True})


# ------------------------------------------------------------ acceptance criteria
def test_a_masked_layer_is_absent_from_every_bar_where_its_mask_applies():
    journey = Journey.from_dict(DATA)
    rows = render(journey, 40)
    masks = expected_mask(journey, rows)
    for (bar, _, layers, _), masked in zip(rows, masks, strict=True):
        assert not (layers & masked), (bar, layers, masked)
    assert all("drums" not in layers and "lead" not in layers for _, t, layers, _ in rows if t < 30)


def test_a_mask_change_applies_on_the_first_bar_where_bar_mod_4_is_0():
    journey = Journey.from_dict(DATA)
    rows = render(journey, 40)
    masks = expected_mask(journey, rows)
    changes = [rows[i][0] for i in range(1, len(rows)) if masks[i] != masks[i - 1]]
    assert changes and all(bar % 4 == 0 for bar in changes)
    first_beat = next(i for i, (_, t, _, _) in enumerate(rows) if t >= 30)
    assert rows[first_beat][0] % 4 != 0 or masks[first_beat] == {"lead"}   # the stage starts mid-phrase here
    drums_back = next(bar for bar, _, layers, _ in rows if "drums" in layers)
    assert drums_back % 4 == 0 and drums_back >= rows[first_beat][0]


def test_an_unmasked_layer_still_follows_the_composer():
    journey = Journey.from_dict(DATA)
    rows = render(journey, 40)
    masks = expected_mask(journey, rows)
    plain = Engine(STYLE, seed=3, samples=False)
    plain.queue_journey(Journey.from_dict({**DATA, "stages": [{k: v for k, v in s.items() if k != "layers"}
                                                             for s in DATA["stages"]]}))
    for (_, _, layers, _), masked in zip(rows, masks, strict=True):
        plain.render_bar()
        assert layers == plain.layers - masked                    # masking only removes, never adds


def test_stopping_the_journey_brings_the_layers_back_at_the_next_phrase():
    journey = Journey.from_dict(DATA)
    rows = render(journey, 16, stop_at=5)
    masks = expected_mask(journey, rows, stop_at=5)
    assert masks[5] == {"drums", "lead"} and masks[8] == frozenset()
    for (_, _, layers, _), masked in zip(rows, masks, strict=True):
        assert not (layers & masked)


def test_music_without_a_journey_plans_every_layer_as_before():
    a = Engine(STYLE, seed=3, samples=False)
    layers = []
    for _ in range(12):
        a.render_bar()
        layers.append(a.layers)
    b = Engine(STYLE, seed=3, samples=False)
    assert layers == [b.composer.plan(bar).layers for bar in range(12)]


def test_the_journey_prompt_describes_the_optional_layers(tmp_path):
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
        print({json.dumps(json.dumps(DATA))})
        """))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    journey, _ = GentleShell(binary=str(script)).journey_from_prompt("drums enter later")
    prompt = json.loads(log.read_text())[-1]
    assert '{"drums": false, "lead": true}' in prompt and "chords, bass, drums, lead, counter" in prompt
    assert journey == Journey.from_dict(DATA)
