"""PM-040: glide tempo and the continuous fields from the TUI, as `ctl tempo` and `ctl glide` do."""
import pytest
from textual.widgets import Input

from gentle_stream.app import ControlsModal, StreamApp
from gentle_stream.engine import GLIDE_FIELDS
from gentle_stream.journey import Journey
from tests.test_app import FakeShell, make_app, text

RAMP = Journey.from_dict({"version": 1, "name": "ramp", "stages": [
    {"name": "Up", "seconds": 120, "to": {"energy": 0.9, "brightness": 0.8}}]})


def spy_glides(player, monkeypatch):
    calls = []
    real = player.engine.queue_glide
    monkeypatch.setattr(player.engine, "queue_glide", lambda fields, seconds: calls.append((fields, seconds))
                        or real(fields, seconds))
    return calls


async def open_controls(pilot):
    await pilot.press("c")
    await pilot.pause(0.2)
    assert isinstance(pilot.app.screen, ControlsModal)
    return pilot.app.screen


@pytest.mark.asyncio
async def test_c_shows_every_continuous_field_with_its_value():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_controls(pilot)
        for name in GLIDE_FIELDS:
            field = screen.query_one(f"#control-{name}", Input)
            assert float(field.value) == pytest.approx(getattr(player.now.style, name))
            assert not field.disabled
        assert screen.query_one("#control-over", Input).value == "60"


@pytest.mark.asyncio
async def test_apply_sends_the_changed_fields_as_one_glide_like_the_cli(monkeypatch):
    app, player = make_app(FakeShell())
    calls = spy_glides(player, monkeypatch)
    async with app.run_test() as pilot:
        screen = await open_controls(pilot)
        screen.query_one("#control-energy", Input).value = "0.7"
        screen.query_one("#control-bpm", Input).value = "90"
        screen.query_one("#control-over", Input).value = "30"
        await pilot.click("#apply")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, ControlsModal)
        assert calls == [({"energy": 0.7, "bpm": 90.0}, 30.0)]          # the call `ctl glide energy=0.7 bpm=90 --over 30` makes
        assert "Gliding" in text(app, "#status")


@pytest.mark.asyncio
async def test_nothing_changed_sends_nothing(monkeypatch):
    app, player = make_app(FakeShell())
    calls = spy_glides(player, monkeypatch)
    async with app.run_test() as pilot:
        await open_controls(pilot)
        await pilot.click("#apply")
        await pilot.pause(0.2)
        assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field, value, over, message", [
    ("energy", "loud", "60", "energy must be a number"),
    ("energy", "0.5", "-1", "over must be between 0 and 3600 seconds"),
    ("energy", "0.5", "4000", "over must be between 0 and 3600 seconds"),
])
async def test_invalid_input_stays_in_the_dialog(monkeypatch, field, value, over, message):
    app, player = make_app(FakeShell())
    calls = spy_glides(player, monkeypatch)
    async with app.run_test() as pilot:
        screen = await open_controls(pilot)
        screen.query_one(f"#control-{field}", Input).value = value
        screen.query_one("#control-over", Input).value = over
        await pilot.click("#apply")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ControlsModal) and calls == []
        assert message in str(screen.query_one("#control-status").render())


@pytest.mark.asyncio
async def test_fields_a_journey_drives_are_shown_as_driven_and_cannot_change():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        player.journey_start(RAMP.to_dict())
        stream = player._stream
        assert stream is not None
        for _ in range(40):
            stream.pull(4096)
            await pilot.pause(0.05)
            if player.engine.journey is not None:
                break
        screen = await open_controls(pilot)
        for name in GLIDE_FIELDS:
            assert screen.query_one(f"#control-{name}", Input).disabled == (name in RAMP.fields)
        assert "driven by the journey" in str(screen.query_one("#control-status").render())


@pytest.mark.asyncio
async def test_the_engine_s_refusal_is_shown_with_the_cli_message(monkeypatch):
    from gentle_stream.engine import JourneyDriven

    app, player = make_app(FakeShell())

    def refuse(fields, seconds):
        raise JourneyDriven('energy is driven by the journey "ramp"; stop it first (gentle-stream journey stop)')

    monkeypatch.setattr(player.engine, "queue_glide", refuse)
    async with app.run_test() as pilot:
        screen = await open_controls(pilot)
        screen.query_one("#control-energy", Input).value = "0.2"
        await pilot.click("#apply")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ControlsModal)
        assert 'energy is driven by the journey "ramp"' in str(screen.query_one("#control-status").render())


def test_the_palette_offers_live_controls():
    assert ("Live controls" in {title for title, _, _ in StreamApp.palette_actions()})
