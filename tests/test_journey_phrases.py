"""PM-032: spoken phrases in journey stages (clips are provided directly: no text-to-speech runs here)."""
import itertools
import threading

import numpy as np
import pytest

from gentle_stream import daemon, speech
from gentle_stream.engine import Engine
from gentle_stream.journey import Journey
from gentle_stream.style import Style
from gentle_stream.synth import SR

BPM = 120.0                      # one bar is 2 s, a phrase boundary every 8 s


def journey(phrases=("Keep going", "Almost there"), every=20, **extra):
    return Journey.from_dict({"version": 1, "name": "talk", "title": "Talk", "end": "sustain", "stages": [
        {"name": "Warm", "seconds": 30, "to": {"energy": 0.4}},
        {"name": "Push", "seconds": 64, "to": {"energy": 0.8}, "phrases": list(phrases), "phrase_every": every,
         **extra},
        {"name": "Rest", "seconds": 40, "to": {"energy": 0.3}}]})


def run(j, seconds=134, provide=True, monkeypatch=None):
    """[(start seconds, text)] of every phrase the journey speaks over `seconds`, and the engine."""
    e = Engine(Style(bpm=BPM), seed=5, samples=False)
    texts = {}
    if provide:
        for text in j.phrases:
            clip = np.full(SR // 2, 0.01)
            texts[id(clip)] = text
            e.provide_phrase(text, clip)
    started = []
    real = e.queue_speech
    e.queue_speech = lambda clip, every=1: started.append((e.samples_out / e.sr, texts.get(id(clip)))) or \
        real(clip, every)
    e.queue_journey(j)
    while e.samples_out < seconds * e.sr:
        e.render_bar()
    return started, e


def test_a_journeys_phrases_ask_for_a_phrase_boundary_not_the_next_bar():
    j = journey()
    e = Engine(Style(bpm=BPM), seed=5, samples=False)
    for text in j.phrases:
        e.provide_phrase(text, np.full(SR // 2, 0.01))
    asked = []
    real = e.queue_speech
    e.queue_speech = lambda clip, every=1: asked.append(every) or real(clip, every)
    e.queue_journey(j)
    while e.samples_out < 134 * e.sr:
        e.render_bar()
    assert asked and set(asked) == {4}


# ------------------------------------------------------------ the journey format
def test_a_stage_keeps_its_phrases_and_interval_and_round_trips():
    j = journey()
    push = j.stages[1]
    assert push.phrases == ("Keep going", "Almost there") and push.phrase_every == 20
    assert j.phrases == ("Keep going", "Almost there")
    again = Journey.from_dict(j.to_dict())
    assert again.stages[1].phrases == push.phrases and again.stages[1].phrase_every == 20
    assert "phrases" not in j.to_dict()["stages"][0]


def test_the_interval_defaults_to_two_minutes():
    j = Journey.from_dict({"version": 1, "name": "x", "stages": [
        {"name": "A", "seconds": 60, "to": {}, "phrases": ["Hi"]}]})
    assert j.stages[0].phrase_every == 120


@pytest.mark.parametrize("stage, message", [
    ({"phrases": "Keep going"}, '"phrases" must be a list of strings'),
    ({"phrases": [3]}, '"phrases" must be a list of strings'),
    ({"phrases": ["x"] * 13}, "at most 12 phrases"),
    ({"phrases": ["x" * 81]}, "1 to 80 characters"),
    ({"phrases": ["   "]}, "1 to 80 characters"),
    ({"phrases": ["Hi"], "phrase_every": 5}, '"phrase_every" must be a number from 10 to 3600'),
    ({"phrases": ["Hi"], "phrase_every": "60"}, '"phrase_every" must be a number from 10 to 3600'),
    ({"phrase_every": 60}, '"phrase_every" needs "phrases"'),
])
def test_bad_phrases_reject_the_journey(stage, message):
    with pytest.raises(ValueError, match=message):
        Journey.from_dict({"version": 1, "name": "x", "stages": [{"name": "A", "seconds": 60, "to": {}, **stage}]})


def test_phrase_text_is_normalised():
    j = Journey.from_dict({"version": 1, "name": "x", "stages": [
        {"name": "A", "seconds": 60, "to": {}, "phrases": ["  Keep   going "]}]})
    assert j.stages[0].phrases == ("Keep going",)


# ------------------------------------------------------------ when they are spoken
def test_phrases_occur_only_in_their_stage_once_per_interval_on_boundaries():
    started, _ = run(journey())
    times = [t for t, _ in started]
    assert len(times) >= 3
    assert all(30 <= t < 94 for t in times)                          # only during "Push" (30 s to 94 s)
    assert all(round(t / 8, 9).is_integer() for t in times)          # every one on a phrase-boundary sample
    assert all(b - a >= 20 for a, b in itertools.pairwise(times))   # at most once per 20 s
    assert times[0] == 32                                            # the stage's first boundary


def test_no_phrase_repeats_immediately_and_all_are_used():
    started, _ = run(journey(phrases=("One", "Two", "Three"), every=10), seconds=94)
    texts = [text for _, text in started]
    assert [t for t, _ in started] == [32, 48, 64, 80]      # 10 s apart at least: every other 8 s boundary
    assert set(texts) == {"One", "Two", "Three"}
    assert all(a != b for a, b in itertools.pairwise(texts))


def test_two_phrases_strictly_alternate_over_a_long_stage():
    long = Journey.from_dict({"version": 1, "name": "x", "stages": [
        {"name": "Long", "seconds": 400, "to": {}, "phrases": ["Left", "Right"], "phrase_every": 10}]})
    texts = [text for _, text in run(long, seconds=400)[0]]
    assert len(texts) == 25                                 # every other 8 s boundary, 0 to 392 s
    assert all(a != b for a, b in itertools.pairwise(texts))


def test_each_stage_counts_its_interval_from_its_own_start():
    two = Journey.from_dict({"version": 1, "name": "x", "stages": [
        {"name": "A", "seconds": 30, "to": {}, "phrases": ["From A"], "phrase_every": 60},
        {"name": "B", "seconds": 60, "to": {}, "phrases": ["From B"], "phrase_every": 60}]})
    started, _ = run(two, seconds=90)
    assert [t for t, _ in started] == [0, 32]               # B does not wait 60 s after A's phrase


def test_the_order_is_the_same_for_the_same_seed():
    first = [text for _, text in run(journey(phrases=("One", "Two", "Three"), every=10), seconds=94)[0]]
    again = [text for _, text in run(journey(phrases=("One", "Two", "Three"), every=10), seconds=94)[0]]
    assert first == again


def test_a_single_phrase_can_repeat():
    started, _ = run(journey(phrases=("Only",), every=10), seconds=94)
    assert [text for _, text in started] == ["Only"] * len(started) and len(started) >= 3


def test_a_phrase_not_rendered_yet_is_skipped_until_it_is_ready():
    started, e = run(journey(), seconds=60, provide=False)
    assert started == []                                             # nothing ready: the music just plays on
    e.provide_phrase("Keep going", np.full(SR // 2, 0.01))
    while e.samples_out < 94 * e.sr:
        e.render_bar()
    assert started and all(text is None for _, text in started)      # spoken once ready (not via our id map)


def test_the_music_is_unchanged_without_phrases():
    plain = Journey.from_dict({"version": 1, "name": "x", "stages": [{"name": "A", "seconds": 40, "to": {}}]})
    a, b = Engine(Style(bpm=BPM), seed=5, samples=False), Engine(Style(bpm=BPM), seed=5, samples=False)
    a.queue_journey(plain)
    b.queue_journey(plain)
    a.provide_phrase("Unused", np.full(SR, 0.3))
    for _ in range(12):
        assert np.array_equal(a.render_bar(), b.render_bar())


def test_phrases_never_change_the_music_s_random_draws():
    """The phrase order has its own generator: the music under a phrase journey is the music without it, ducked."""
    _, e1 = run(journey(), seconds=20)
    _, e2 = run(journey(phrases=("A", "B", "C"), every=10), seconds=20)
    assert e1.style == e2.style


# ------------------------------------------------------------ rendered ahead, in the background
def test_starting_a_journey_renders_its_phrases_in_the_background(monkeypatch):
    from tests.test_daemon import fake_player

    done = threading.Event()
    rendered = []

    def fake_render(text, sr=SR):
        assert threading.current_thread() is not threading.main_thread()
        rendered.append(text)
        if len(rendered) == 2:
            done.set()
        return np.full(SR // 4, 0.01)

    monkeypatch.setattr(speech, "render", fake_render)
    player = fake_player()
    answer = daemon.handle(player, {"cmd": "journey_start", "journey": journey().to_dict()})
    assert answer["ok"] and done.wait(5)
    assert sorted(rendered) == ["Almost there", "Keep going"]
    for _ in range(50):
        if set(player.engine._phrase_clips) == {"Keep going", "Almost there"}:
            break
        threading.Event().wait(0.02)
    assert set(player.engine._phrase_clips) == {"Keep going", "Almost there"}


def test_without_a_backend_the_journey_plays_on_and_says_why_once(monkeypatch, caplog):
    from tests.test_daemon import fake_player

    calls = []

    def failing(text, sr=SR):
        calls.append(text)
        raise speech.SpeechError(speech.NO_BACKEND)

    monkeypatch.setattr(speech, "render", failing)
    with caplog.at_level("WARNING", logger="gentle_stream.speech"):
        thread = speech.prerender(("A", "B"), SR, lambda text, clip: pytest.fail("delivered"))
        thread.join(5)
    assert calls == ["A"]                                            # the first failure stops the rest
    assert [r.getMessage() for r in caplog.records] == [
        f"journey phrases will not be spoken: {speech.NO_BACKEND}"]
    player = fake_player()
    assert daemon.handle(player, {"cmd": "journey_start", "journey": journey().to_dict()})["ok"]


def test_render_bar_never_runs_text_to_speech(monkeypatch):
    monkeypatch.setattr(speech, "render", lambda *a, **k: pytest.fail("text-to-speech ran on the render thread"))
    run(journey(), seconds=94)


def test_the_journey_prompt_offers_phrases_without_health_claims(monkeypatch):
    from gentle_stream.bridge import GentleShell

    sent = []
    answer = journey().to_dict()
    monkeypatch.setattr(GentleShell, "_run", lambda self, cmd: sent.append(cmd) or __import__("json").dumps(answer))
    GentleShell(binary="gentle-shell").journey_from_prompt("a run with encouragement")
    text = sent[0][-1]                                     # the prompt the model receives
    assert '"phrases"' in text and '"phrase_every"' in text
    assert "never claim health, therapeutic or medical effects" in text
