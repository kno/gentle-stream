"""While a journey plays, the title is the journey and its stage, not the name of the style it started from (the
maintainer saw "Midnight Rain" over a journey called "Train"); the TUI and the broadcast picture say the same."""
import pytest

from gentle_stream.broadcast_view import view_text
from gentle_stream.engine import Engine
from gentle_stream.journey import BUILTIN
from gentle_stream.lines import title_line
from gentle_stream.player import Player
from gentle_stream.style import Style
from tests.test_app import FakeShell, make_app, text
from tests.test_player import FakeStream


def playing_journey() -> Player:
    """A player whose audible bar belongs to the warm-up journey."""
    player = Player(Engine(Style(name="Midnight Rain"), seed=1, samples=False), stream_factory=FakeStream,
                    prebuffer=0.3)
    player.engine.queue_journey(BUILTIN["warm-up"])
    player.start()
    stream = player._stream
    assert isinstance(stream, FakeStream)
    for _ in range(400):
        if player.now.journey is not None:
            break
        stream.pull(1024)
    return player


def test_without_a_journey_the_title_is_the_style():
    style = Style(name="Midnight Rain")
    assert title_line(style, None) == "♪ Midnight Rain"


def test_with_a_journey_the_title_is_the_journey_and_its_stage():
    player = playing_journey()
    try:
        journey = BUILTIN["warm-up"]
        expected = f"♪ {journey.title} · {journey.stages[0].name}"
        assert player.now.journey is not None
        assert title_line(player.now.style, player.now.journey) == expected
        assert view_text(player).title == expected                  # the broadcast picture says the same
    finally:
        player.close()


def pull(player: Player) -> None:
    """The fake stream plays only when pulled: half a second of audio, so the journey's bars become audible."""
    stream = player._stream
    assert isinstance(stream, FakeStream)
    for _ in range(20):
        stream.pull(1024)


@pytest.mark.asyncio
async def test_the_tui_title_follows_the_journey_and_comes_back_when_it_stops():
    app, player = make_app(FakeShell())
    journey = BUILTIN["warm-up"]
    async with app.run_test() as pilot:
        assert text(app, "#title") == "♪ Midnight Rain"
        player.journey_start(journey.to_dict())
        for _ in range(60):
            pull(player)
            await pilot.pause(0.1)
            if journey.title in text(app, "#title"):
                break
        assert text(app, "#title") == f"♪ {journey.title} · {journey.stages[0].name}"
        player.engine.stop_journey()
        for _ in range(60):
            pull(player)
            await pilot.pause(0.1)
            if journey.title not in text(app, "#title"):
                break
        assert text(app, "#title") == "♪ Midnight Rain"
