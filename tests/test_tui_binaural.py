"""PM-041: the binaural layer from the TUI (B), making the same requests as `ctl binaural on|set|off`."""
import pytest
from textual.widgets import Input

from gentle_stream.app import BinauralModal, StreamApp
from gentle_stream.binaural import Binaural
from tests.test_app import FakeShell, make_app, text


def spy(player, monkeypatch):
    calls = []
    real = player.engine.queue_binaural
    monkeypatch.setattr(player.engine, "queue_binaural",
                        lambda setting, seconds=0.0: calls.append((setting, seconds)) or real(setting, seconds))
    return calls


async def open_binaural(pilot):
    await pilot.press("B")
    await pilot.pause(0.2)
    assert isinstance(pilot.app.screen, BinauralModal)
    return pilot.app.screen


def fill(screen, **values):
    for name, value in values.items():
        screen.query_one(f"#binaural-{name}", Input).value = str(value)


@pytest.mark.asyncio
async def test_with_the_layer_off_apply_turns_it_on_like_ctl_binaural_on(monkeypatch):
    app, player = make_app(FakeShell())
    calls = spy(player, monkeypatch)
    async with app.run_test() as pilot:
        screen = await open_binaural(pilot)
        assert screen.query_one("#binaural-carrier", Input).value == "200"     # the defaults when off
        fill(screen, beat=10, over=20)
        await pilot.click("#apply")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, BinauralModal)
        assert calls == [(Binaural(200, 10, 0.05), 20.0)]        # `ctl binaural on --beat 10 --over 20`
        assert "Binaural" in text(app, "#status")


@pytest.mark.asyncio
async def test_with_the_layer_on_apply_glides_only_what_changed_like_ctl_binaural_set(monkeypatch):
    app, player = make_app(FakeShell())
    player.engine.queue_binaural(Binaural(180, 6, 0.04))
    calls = spy(player, monkeypatch)
    async with app.run_test() as pilot:
        screen = await open_binaural(pilot)
        assert screen.query_one("#binaural-carrier", Input).value == "180"     # the values it plays
        fill(screen, level=0.06, over=30)
        await pilot.click("#apply")
        await pilot.pause(0.2)
        assert calls == [(Binaural(180, 6, 0.06), 30.0)]         # `ctl binaural set --level 0.06 --over 30`


@pytest.mark.asyncio
async def test_the_dialog_makes_the_requests_the_cli_makes(monkeypatch):
    """Over the background player these are different requests: `binaural` (on) and `binaural_set` (only the
    values given)."""
    app, player = make_app(FakeShell())
    requests = []
    monkeypatch.setattr(player, "set_binaural", lambda setting, seconds=0.0: requests.append(("on", setting, seconds)))
    monkeypatch.setattr(player, "glide_binaural", lambda values, seconds=0.0: requests.append(("set", values, seconds)))
    async with app.run_test() as pilot:
        screen = await open_binaural(pilot)                    # off: the dialog turns it on
        fill(screen, beat=10, over=20)
        await pilot.click("#apply")
        await pilot.pause(0.2)
        player.engine.queue_binaural(Binaural(180, 6, 0.04))   # now it plays: the dialog sets
        player.engine.render_bar()
        screen = await open_binaural(pilot)
        fill(screen, level=0.06, over=30)
        await pilot.click("#apply")
        await pilot.pause(0.2)
    assert requests == [("on", Binaural(200, 10, 0.05), 20.0), ("set", {"level": 0.06}, 30.0)]


@pytest.mark.asyncio
async def test_off_fades_the_layer_out_like_ctl_binaural_off(monkeypatch):
    app, player = make_app(FakeShell())
    player.engine.queue_binaural(Binaural())
    calls = spy(player, monkeypatch)
    async with app.run_test() as pilot:
        await open_binaural(pilot)
        await pilot.click("#off")
        await pilot.pause(0.2)
        assert calls and calls[0][0] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field, value, message", [
    ("carrier", 20, "carrier must be between 40 and 1000 Hz"),
    ("beat", 50, "beat must be between 0.5 and 40 Hz"),
    ("level", 0.2, "level must be between 0 and 0.08"),
    ("beat", "fast", "beat must be a number"),
    ("over", 4000, "over must be between 0 and 3600 seconds"),
])
async def test_ranges_are_enforced_before_sending(monkeypatch, field, value, message):
    app, player = make_app(FakeShell())
    calls = spy(player, monkeypatch)
    async with app.run_test() as pilot:
        screen = await open_binaural(pilot)
        fill(screen, **{field: value})
        await pilot.click("#apply")
        await pilot.pause(0.2)
        assert isinstance(app.screen, BinauralModal) and calls == []
        assert message in str(screen.query_one("#binaural-status").render())


@pytest.mark.asyncio
async def test_a_journey_that_owns_the_layer_refuses_with_the_cli_message(monkeypatch):
    from gentle_stream.engine import JourneyDriven

    app, player = make_app(FakeShell())

    def refuse(setting, seconds=0.0):
        raise JourneyDriven('binaural is driven by the journey "x"; stop it first (gentle-stream journey stop)')

    monkeypatch.setattr(player.engine, "queue_binaural", refuse)
    async with app.run_test() as pilot:
        screen = await open_binaural(pilot)
        await pilot.click("#apply")
        await pilot.pause(0.2)
        assert 'binaural is driven by the journey "x"' in str(screen.query_one("#binaural-status").render())


def test_the_local_player_refuses_a_set_while_the_layer_is_off_like_the_daemon():
    from gentle_stream.engine import Engine
    from gentle_stream.player import Player
    from gentle_stream.style import Style
    from tests.test_player import FakeStream

    player = Player(Engine(Style(), seed=1, samples=False), stream_factory=FakeStream)
    with pytest.raises(ValueError, match="binaural is off; turn it on first"):
        player.glide_binaural({"beat": 8.0}, 10)


@pytest.mark.asyncio
async def test_the_dialog_makes_no_claims_about_effects():
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_binaural(pilot)
        shown = " ".join(str(w.render()) for w in screen.query("Static"))
        assert "headphones" in shown
        for word in ("focus", "sleep", "relax", "health", "anxiety"):
            assert word not in shown.lower()


def test_the_palette_offers_binaural():
    assert "Binaural" in {title for title, _, _ in StreamApp.palette_actions()}
