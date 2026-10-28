"""PM-036 in the TUI: record the session with `r`, see it in the status line, and find every action in the palette."""
from typing import cast

import pytest
from scipy.io import wavfile
from textual.binding import Binding
from textual.widgets import Input

from gentle_stream.app import RecordDialog, StreamApp
from tests.test_app import FakeShell, make_app, text


@pytest.mark.asyncio
async def test_r_asks_for_a_file_and_records_until_r_again(tmp_path):
    app, player = make_app(FakeShell())
    path = tmp_path / "session.wav"
    async with app.run_test() as pilot:
        await pilot.press("r")
        await pilot.pause(0.1)
        assert isinstance(app.screen, RecordDialog)
        dialog_input = app.screen.query_one("#record-path", Input)
        assert str(dialog_input.value).endswith(".wav")            # a dated file in the home folder is proposed
        dialog_input.value = str(path)
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, RecordDialog)
        assert player.recording is not None and player.recording[0] == path
        assert "● REC" in text(app, "#state")
        await pilot.press("r")                                    # r again stops
        await pilot.pause(0.1)
        assert player.recording is None
        assert "Saved" in text(app, "#status") and str(path) in text(app, "#status")
    assert wavfile.read(path)[1].ndim == 2


@pytest.mark.asyncio
async def test_the_dialog_shows_why_a_file_cannot_be_used(tmp_path):
    app, player = make_app(FakeShell())
    (tmp_path / "taken.wav").write_bytes(b"x")
    async with app.run_test() as pilot:
        await pilot.press("r")
        await pilot.pause(0.1)
        app.screen.query_one("#record-path", Input).value = str(tmp_path / "taken.wav")
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert isinstance(app.screen, RecordDialog)                 # still open, with the reason
        assert "already exists" in str(app.screen.query_one("#record-status").render())
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert player.recording is None
    assert (tmp_path / "taken.wav").read_bytes() == b"x"


@pytest.mark.asyncio
async def test_quitting_saves_the_recording(tmp_path):
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.press("r")
        await pilot.pause(0.1)
        app.screen.query_one("#record-path", Input).value = str(tmp_path / "s.wav")
        await pilot.press("enter")
        await pilot.pause(0.3)
    assert player.recording is None and wavfile.read(tmp_path / "s.wav")[0] == player.engine.sr


# ------------------------------------------------------------ the command palette
def test_every_key_action_is_in_the_palette():
    keyed = {b.action for b in cast(list[Binding], StreamApp.BINDINGS) if b.show}   # hidden keys are navigation
    in_palette = {action for _, _, action in StreamApp.palette_actions()}
    assert keyed - {"volume(1)", "volume(-1)"} <= in_palette          # fine volume steps stay keys only
    assert "record" in in_palette


@pytest.mark.asyncio
async def test_the_palette_finds_and_runs_an_action():
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause(0.2)
        await pilot.press(*"record")
        await pilot.pause(0.5)
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, RecordDialog)
