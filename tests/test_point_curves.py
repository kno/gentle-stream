"""PM-038: point-list curves shape a stage's ramp freely."""
import pytest

from gentle_stream.bridge import journey_rules
from gentle_stream.journey import Journey, shape, stage_diff

POINTS = [[0, 0], [0.3, 0.8], [1, 1]]


def make(curve):
    return Journey.from_dict({"version": 1, "name": "x", "stages": [
        {"name": "Rise", "seconds": 100, "to": {"energy": 1.0}, "curve": curve}]})


# ------------------------------------------------------------ values follow the polyline
@pytest.mark.parametrize("progress, expected", [
    (0.0, 0.0), (0.3, 0.8), (1.0, 1.0),                 # at the points
    (0.15, 0.4), (0.65, 0.9), (0.1, 0.8 / 3),           # between them, linearly
])
def test_values_match_the_polyline_at_and_between_points(progress, expected):
    j = make(POINTS)
    assert j.at(progress * 100, {"energy": 0.0})[2]["energy"] == pytest.approx(expected)
    assert shape(j.stages[0].curve, progress) == pytest.approx(expected)


def test_a_point_curve_round_trips_as_a_list_of_points():
    j = make(POINTS)
    assert j.stages[0].curve == ((0.0, 0.0), (0.3, 0.8), (1.0, 1.0))
    data = j.to_dict()
    assert data["stages"][0]["curve"] == [[0.0, 0.0], [0.3, 0.8], [1.0, 1.0]]
    assert Journey.from_dict(data).to_dict() == data


def test_a_curve_can_go_down_and_back_up():
    j = make([[0, 0], [0.5, 1], [0.75, 0.2], [1, 1]])
    assert j.at(75, {"energy": 0.0})[2]["energy"] == pytest.approx(0.2)


# ------------------------------------------------------------ invalid lists name the offending point
@pytest.mark.parametrize("curve, message", [
    ([[0, 0]], "\"curve\" must be a curve name or 2 to 16 \\[progress, fraction\\] points"),
    ([[i / 16, i / 16] for i in range(17)], "\"curve\" must be a curve name or 2 to 16 \\[progress, fraction\\] points"),
    ([[0, 0], [0.5], [1, 1]], "curve point 2 \\[0.5\\] must be \\[progress, fraction\\]"),
    ([[0, 0], ["a", 1], [1, 1]], "curve point 2 \\['a', 1\\] must be \\[progress, fraction\\]"),
    ([[0, 0], [0.5, 1.2], [1, 1]], "curve point 2 \\[0.5, 1.2\\] must have both values from 0 to 1"),
    ([[0, 0], [0.6, 0.5], [0.4, 0.7], [1, 1]], "curve point 3 \\[0.4, 0.7\\] must come after the previous point"),
    ([[0, 0], [0.5, 0.5], [0.5, 0.7], [1, 1]], "curve point 3 \\[0.5, 0.7\\] must come after the previous point"),
    ([[0, 0.2], [1, 1]], "curve point 1 \\[0, 0.2\\] must be \\[0, 0\\]: a curve starts at \\[0, 0\\]"),
    ([[0, 0], [1, 0.9]], "curve point 2 \\[1, 0.9\\] must be \\[1, 1\\]: a curve ends at \\[1, 1\\]"),
])
def test_invalid_point_lists_are_refused_with_the_offending_point(curve, message):
    with pytest.raises(ValueError, match=f"stage 1: {message}"):
        make(curve)


def test_named_curves_are_unchanged():
    assert make("ease-in").stages[0].curve == "ease-in"
    assert make("ease-in").at(50, {"energy": 0.0})[2]["energy"] == pytest.approx(0.25)
    assert "curve" not in make("linear").to_dict()["stages"][0]


def test_an_unknown_curve_name_still_falls_back_to_linear_with_a_warning():
    warnings: list[str] = []
    j = Journey.from_dict({"version": 1, "name": "x", "stages": [
        {"name": "Rise", "seconds": 100, "to": {}, "curve": "wobble"}]}, warnings)
    assert j.stages[0].curve == "linear" and warnings == ["stage 1: unknown curve 'wobble'; using linear"]


def test_the_diff_names_a_point_curve():
    assert stage_diff(make("linear"), make(POINTS)) == ["  ~ Rise: curve linear -> 3 points"]


def test_the_journey_rules_offer_point_curves():
    assert "[progress, fraction]" in journey_rules()
