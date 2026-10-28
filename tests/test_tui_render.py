"""PM-044: render to a WAV from the TUI (w), writing the bytes `gentle-stream render` writes with the same options."""
import json

import pytest
from textual.widgets import Checkbox, Input, Select

from gentle_stream import main
from gentle_stream.app import RenderModal, StreamApp
from tests.test_app import FakeShell, make_app


@pytest.fixture(autouse=True)
def cache(monkeypatch, tmp_path):
    """A private cache: the installed soundfont (if any) must not decide what these renders sound like."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


async def open_render(pilot):
    await pilot.press("w")
    await pilot.pause(0.1)
    assert isinstance(pilot.app.screen, RenderModal)
    return pilot.app.screen


def fill(screen, **values):
    for name, value in values.items():
        screen.query_one(f"#render-{name}", Input).value = str(value)


async def render(pilot):
    await pilot.click("#render")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause(0.2)


def status(screen) -> str:
    return str(screen.query_one("#render-status").render())


@pytest.mark.asyncio
async def test_the_current_style_renders_to_the_bytes_render_writes(tmp_path, capsys):
    from typing import Any

    from gentle_stream.engine import Engine
    from gentle_stream.player import Player
    from gentle_stream.style import Style, genre_names
    from tests.test_player import FakeStream

    out = tmp_path / "tui.wav"
    playing = Style(name="Not the default", genre=genre_names()[-1], energy=0.8, brightness=0.2)
    player = Player(Engine(playing, seed=1), stream_factory=lambda **k: FakeStream(**k), prebuffer=0.3)
    shell: Any = FakeShell()   # the fake Gentle Shell of tests/test_app.py
    app = StreamApp(player, shell)
    async with app.run_test() as pilot:
        style = player.now.style
        assert style.genre == genre_names()[-1]
        screen = await open_render(pilot)
        fill(screen, path=out, seconds=2, seed=7)
        await render(pilot)
        assert not isinstance(app.screen, RenderModal)
    (tmp_path / "style.json").write_text(json.dumps(style.to_dict()))
    assert main(["render", str(tmp_path / "cli.wav"), "--seconds", "2", "--seed", "7",
                 "--mood-file", str(tmp_path / "style.json")]) == 0
    assert capsys.readouterr().out == f"wrote {tmp_path / 'cli.wav'}: 2 s, {style.genre}, seed 7\n"
    assert out.read_bytes() == (tmp_path / "cli.wav").read_bytes()


@pytest.mark.asyncio
async def test_a_journey_procedural_render_equals_the_cli_one_and_reports_like_it(tmp_path, capsys):
    out = tmp_path / "tui.wav"
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        style = player.now.style
        screen = await open_render(pilot)
        fill(screen, path=out, seconds=3, seed=11)
        screen.query_one("#render-journey", Select).value = "wind-down"
        screen.query_one("#render-procedural", Checkbox).value = True
        await pilot.click("#render")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause(0.2)
        shown = str(app.query_one("#status").render())
    (tmp_path / "style.json").write_text(json.dumps(style.to_dict()))
    assert main(["render", str(tmp_path / "cli.wav"), "--seconds", "3", "--seed", "11", "--journey", "wind-down",
                 "--procedural", "--mood-file", str(tmp_path / "style.json")]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed.endswith(", seed 11, journey wind-down")
    assert printed.replace(str(tmp_path / "cli.wav"), str(out)) in shown
    assert out.read_bytes() == (tmp_path / "cli.wav").read_bytes()


@pytest.mark.asyncio
async def test_a_blank_seed_picks_one_and_says_which(tmp_path):
    out = tmp_path / "tui.wav"
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_render(pilot)
        fill(screen, path=out, seconds=1, seed="")
        await render(pilot)
        assert ", seed " in str(app.query_one("#status").render())
    assert out.stat().st_size > 44


@pytest.mark.asyncio
@pytest.mark.parametrize("field, value, message", [
    ("seconds", 0, "seconds must be a number above 0 and at most 3600"),
    ("seconds", 4000, "seconds must be a number above 0 and at most 3600"),
    ("seconds", "long", "seconds must be a number above 0 and at most 3600"),
    ("seed", -1, "seed must be a non-negative integer"),
    ("path", "", "type the WAV file to write"),
])
async def test_invalid_options_stay_in_the_dialog(tmp_path, field, value, message):
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_render(pilot)
        fill(screen, path=tmp_path / "x.wav", seconds=1, seed=1)
        fill(screen, **{field: value})
        await render(pilot)
        assert isinstance(app.screen, RenderModal) and status(screen) == message
    assert not (tmp_path / "x.wav").exists()


@pytest.mark.asyncio
async def test_a_path_that_cannot_be_written_says_so_like_the_cli(tmp_path, capsys):
    out = tmp_path / "missing" / "x.wav"
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_render(pilot)
        fill(screen, path=out, seconds=1, seed=1)
        await render(pilot)
        assert isinstance(app.screen, RenderModal)
        shown = status(screen)
    assert main(["render", str(out), "--seconds", "1", "--seed", "1"]) == 1
    assert shown == capsys.readouterr().err.strip().removeprefix("gentle-stream: ")


@pytest.mark.asyncio
async def test_everything_fits_in_80_by_24():
    app, _ = make_app(FakeShell())
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_render(pilot)
        for name in ("render-path", "render-seconds", "render-seed", "render-journey", "render-procedural",
                     "render", "cancel", "render-status"):
            region = screen.query_one(f"#{name}").region
            assert region.width > 0 and region.right <= 80 and region.bottom <= 24, name


@pytest.mark.asyncio
async def test_the_options_reach_the_function_render_uses(tmp_path, monkeypatch):
    """`procedural` changes the bytes only with the soundfont or a voice pack installed, so it is checked here."""
    import gentle_stream

    calls = []
    monkeypatch.setattr(gentle_stream, "render_style",
                        lambda out, seconds, seed, style, procedural, journey=None:
                        calls.append((out, seconds, seed, style, procedural, journey)) or "wrote it")
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_render(pilot)
        fill(screen, path=tmp_path / "x.wav", seconds=5, seed=3)
        screen.query_one("#render-journey", Select).value = "wind-down"
        screen.query_one("#render-procedural", Checkbox).value = True
        await render(pilot)
    assert calls == [(str(tmp_path / "x.wav"), 5.0, 3, player.now.style, True, "wind-down")]


def test_the_palette_offers_render():
    assert "Render to a file" in {title for title, _, _ in StreamApp.palette_actions()}
