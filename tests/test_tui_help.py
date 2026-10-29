"""The footer cannot show every key; `?` lists them all, with every palette action, in a popup."""
import pytest
from textual.binding import Binding
from textual.containers import VerticalScroll

from gentle_stream.app import HelpModal, StreamApp
from tests.test_app import FakeShell, make_app


async def open_help(pilot):
    await pilot.press("question_mark")
    await pilot.pause(0.2)
    assert isinstance(pilot.app.screen, HelpModal)
    return pilot.app.screen


def shown(screen) -> str:
    return "\n".join(str(row.render()) for row in screen.query(".help-row"))


@pytest.mark.asyncio
async def test_question_mark_lists_every_key_and_every_action():
    app, _ = make_app(FakeShell())
    async with app.run_test(size=(100, 40)) as pilot:
        screen = await open_help(pilot)
        text = shown(screen)
        for binding in (b for b in StreamApp.BINDINGS if isinstance(b, Binding)):
            if binding.show and binding.action != "help":
                assert binding.description in text, binding.description
        for title, _, _ in StreamApp.palette_actions():
            assert title in text, title
        for key in ("space", "L", "M", "o", "ctrl+p"):
            assert key in text, key


@pytest.mark.asyncio
async def test_it_scrolls_in_a_small_terminal_and_closes_with_escape_or_question_mark():
    app, _ = make_app(FakeShell())
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_help(pilot)
        box = screen.query_one(VerticalScroll)
        assert box.region.bottom <= 24 and box.region.right <= 80
        assert box.max_scroll_y > 0                                  # more rows than fit: it scrolls, nothing cut
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, HelpModal)
        await open_help(pilot)
        await pilot.press("question_mark")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, HelpModal)


def test_the_footer_shows_the_question_mark_and_the_palette_offers_it():
    help_binding = next(b for b in StreamApp.BINDINGS if isinstance(b, Binding) and b.action == "help")
    assert help_binding.key == "question_mark" and help_binding.show
    assert "Keys" in {title for title, _, _ in StreamApp.palette_actions()}
