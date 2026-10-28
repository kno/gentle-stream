"""PM-017: a genre step carries the melody's motif head into the new piece."""
import numpy as np

from gentle_stream.composer import Composer
from gentle_stream.engine import Engine
from gentle_stream.journey import Journey, Stage
from gentle_stream.style import Style

STYLE = Style(genre="ambient", key="C", mode="lydian")
JOURNEY = Journey("motif", (
    Stage("Ambient", 20, {"bpm": 70.0}, genre="ambient"),
    Stage("Synthwave", 60, {"bpm": 70.0}, genre="synthwave"),
))


def head(motif):
    return tuple(note for note in motif if note[0] < 4)


def test_default_construction_is_unchanged():
    a = Composer(STYLE, 11, 48)
    b = Composer(STYLE, 11, 48, motif=None)
    assert a.motif == b.motif and a.anchor == b.anchor
    assert [a.plan(bar) for bar in range(48)] == [b.plan(bar) for bar in range(48)]


def test_the_new_motif_starts_with_the_carried_head():
    old = Composer(STYLE, 11, 48)
    carried = head(old.motif)
    new = Composer(Style(genre="synthwave", key="E", mode="minor"), 99, 52, motif=carried)
    assert head(new.motif) == carried                       # scale steps: the same head in the new key
    assert len(new.motif) > len(carried)                    # with a fresh tail
    assert all(note[0] >= 4 for note in new.motif[len(carried):])


def test_the_carried_head_is_realised_in_the_new_key():
    old = Composer(STYLE, 11, 48)
    new = Composer(Style(genre="synthwave", key="E", mode="minor"), 99, 52, motif=head(old.motif))
    e_minor = {(52 + step) % 12 for step in (0, 2, 3, 5, 7, 8, 10)}
    scale = new._scale(0)
    pitches = [scale[int(np.clip(new.anchor + step, 0, len(scale) - 1))] for _, step, _ in head(new.motif)]
    assert {p % 12 for p in pitches} <= e_minor


def test_a_much_faster_new_tempo_augments_the_head():
    old = Composer(STYLE, 11, 48)
    carried = head(old.motif)
    new = Composer(Style(genre="synthwave", key="E", mode="minor", bpm=130), 99, 52, motif=carried, tempo_ratio=2.0)
    assert new.motif == tuple((beat * 2, step, length * 2) for beat, step, length in carried)


def test_later_cycles_keep_developing_from_the_carried_head():
    old = Composer(STYLE, 11, 48)
    carried = head(old.motif)
    new = Composer(Style(genre="synthwave", key="E", mode="minor"), 99, 52, motif=carried)
    for bar in range(0, 200, 8):
        new.plan(bar)
    assert head(new.motif) == carried


def test_a_genre_step_in_a_journey_carries_the_head():
    e = Engine(STYLE, seed=4, samples=False)
    e.queue_journey(JOURNEY)
    e.render_bar()
    while True:
        before, piece = head(e.composer.motif), e.piece
        e.render_bar()
        if e.piece != piece:
            break
    assert e.style.genre == "synthwave"
    assert head(e.composer.motif) == before


def test_next_still_starts_a_fresh_motif():
    e = Engine(STYLE, seed=4, samples=False)
    e.render_bar()
    before = head(e.composer.motif)
    e.queue_next()
    e.render_bar()
    assert head(e.composer.motif) != before
