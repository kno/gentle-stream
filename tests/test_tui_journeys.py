"""PM-039: everything `journey` does on the command line, from the TUI."""
import json

import pytest
from textual.widgets import Input, OptionList

from gentle_stream.app import (
    JourneyEditModal,
    JourneyFileModal,
    JourneyMenu,
    JourneyPickerModal,
    JourneyShowModal,
    SaveDialog,
)
from gentle_stream.journey import BUILTIN, Journey, JourneyStore, edit_preview
from tests.test_app import FakeShell, make_app, text

OLD = Journey.from_dict({"version": 1, "name": "talk", "title": "Talk", "end": "sustain", "stages": [
    {"name": "Warm", "seconds": 60, "to": {"energy": 0.3}},
    {"name": "Build", "seconds": 120, "to": {"energy": 0.6}}]})
LONGER = Journey.from_dict({"version": 1, "name": "talk", "title": "Talk", "end": "sustain", "stages": [
    {"name": "Warm", "seconds": 60, "to": {"energy": 0.3}},
    {"name": "Build", "seconds": 300, "to": {"energy": 0.8}}]})


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


class EditShell(FakeShell):
    def __init__(self, answer=LONGER, error=None):
        super().__init__()
        self.edit_answer, self.edit_error, self.edits = answer, error, []

    def journey_edit(self, current, position, request):
        from gentle_stream.bridge import InterpretError
        self.edits.append((current, position, request))
        if self.edit_error:
            raise InterpretError(self.edit_error)
        return self.edit_answer, None


async def choose(pilot, option_id):
    """Highlight `option_id` in the open screen's option list and press Enter."""
    options = pilot.app.screen.query_one(OptionList)
    ids = [options.get_option_at_index(i).id for i in range(options.option_count)]
    options.highlighted = ids.index(option_id)
    await pilot.press("enter")
    await pilot.pause(0.2)


async def drive(pilot, player, until=lambda: False, seconds=2.0):
    """Pull audio from the fake device so the player renders bars (nothing else consumes it in these tests)."""
    stream = player._stream
    assert stream is not None
    for _ in range(int(seconds / 0.05)):
        stream.pull(4096)
        await pilot.pause(0.05)
        if until():
            return


async def with_journey(pilot, player, journey=OLD):
    player.journey_start(journey.to_dict())
    await drive(pilot, player, lambda: player.engine.journey is not None)
    if player.engine.journey is None:
        raise AssertionError("the journey did not start")
    await drive(pilot, player, lambda: player.now.journey is not None)   # and audible, for the snapshot


# ------------------------------------------------------------ edit the running journey
@pytest.mark.asyncio
async def test_edit_shows_the_cli_diff_and_applies_only_after_confirming():
    shell = EditShell()
    app, player = make_app(shell)
    async with app.run_test() as pilot:
        await with_journey(pilot, player)
        await pilot.press("j")
        await pilot.pause(0.1)
        assert isinstance(app.screen, JourneyMenu)
        await choose(pilot, "edit")
        assert isinstance(app.screen, JourneyEditModal)
        app.screen.query_one("#edit-prompt", Input).value = "make the build-up longer"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)
        shown = str(app.screen.query_one("#edit-diff").render())
        _, position, request = shell.edits[0]
        assert request == "make the build-up longer" and position.startswith('stage ')
        snap = player.now.journey
        assert snap is not None
        for line in edit_preview(OLD, snap.stage, snap.progress, LONGER)[1]:
            assert line.strip() in shown                             # the same lines `journey edit` prints
        assert player.engine.journey == OLD                          # nothing applied yet
        await pilot.click("#apply")
        await drive(pilot, player, lambda: player.engine.journey != OLD)
        assert not isinstance(app.screen, JourneyEditModal)
        assert player.engine.journey is not None and player.engine.journey.to_dict() == LONGER.to_dict()
        assert "Edited journey" in text(app, "#status")


@pytest.mark.asyncio
async def test_cancelling_an_edit_leaves_the_journey_alone():
    app, player = make_app(EditShell())
    async with app.run_test() as pilot:
        await with_journey(pilot, player)
        await pilot.press("j")
        await pilot.pause(0.1)
        await choose(pilot, "edit")
        app.screen.query_one("#edit-prompt", Input).value = "longer"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)
        await pilot.press("escape")
        await drive(pilot, player, seconds=0.5)
        assert player.engine.journey == OLD


@pytest.mark.asyncio
async def test_an_edit_error_is_shown_in_the_dialog():
    app, player = make_app(EditShell(error="invalid journey: stage 1: seconds must be above 0"))
    async with app.run_test() as pilot:
        await with_journey(pilot, player)
        await pilot.press("j")
        await pilot.pause(0.1)
        await choose(pilot, "edit")
        app.screen.query_one("#edit-prompt", Input).value = "nonsense"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)
        assert "invalid journey" in str(app.screen.query_one("#edit-diff").render())
        assert app.screen.query_one("#apply").disabled


@pytest.mark.asyncio
async def test_edit_without_a_running_journey_says_so():
    app, _ = make_app(EditShell())
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.pause(0.1)
        await choose(pilot, "edit")
        assert not isinstance(app.screen, JourneyEditModal)
        assert "no journey is running" in text(app, "#status")


# ------------------------------------------------------------ save, delete, show
@pytest.mark.asyncio
async def test_save_as_stores_the_running_journey_under_a_name():
    app, player = make_app(EditShell())
    async with app.run_test() as pilot:
        await with_journey(pilot, player)
        await pilot.press("j")
        await pilot.pause(0.1)
        await choose(pilot, "save")
        assert isinstance(app.screen, SaveDialog)
        app.screen.query_one(Input).value = "Evening talk"
        await pilot.press("enter")
        await pilot.pause(0.2)
        saved = JourneyStore().get("Evening talk")
        assert saved is not None and saved.stages == OLD.stages
        assert 'Saved journey "Evening talk"' in text(app, "#status")


@pytest.mark.asyncio
async def test_d_deletes_a_saved_journey_and_leaves_built_ins():
    JourneyStore().save("Old one", OLD)
    app, _ = make_app(EditShell())
    async with app.run_test() as pilot:
        await pilot.press("J")
        await pilot.pause(0.1)
        options = app.screen.query_one(OptionList)
        ids = [options.get_option_at_index(i).id for i in range(options.option_count)]
        options.highlighted = ids.index("builtin:warm-up")
        await pilot.press("d")                                      # a built-in cannot be deleted
        await pilot.pause(0.1)
        assert "built-in" in str(app.screen.query_one("#journey-picker-status").render())
        options.highlighted = ids.index("saved:Old one")
        await pilot.press("d")
        await pilot.pause(0.1)
        assert JourneyStore().get("Old one") is None
        assert "saved:Old one" not in [options.get_option_at_index(i).id for i in range(options.option_count)]


@pytest.mark.asyncio
async def test_v_shows_a_journey():
    app, _ = make_app(EditShell())
    async with app.run_test() as pilot:
        await pilot.press("J")
        await pilot.pause(0.1)
        options = app.screen.query_one(OptionList)
        ids = [options.get_option_at_index(i).id for i in range(options.option_count)]
        options.highlighted = ids.index("builtin:warm-up")
        await pilot.press("v")
        await pilot.pause(0.2)
        assert isinstance(app.screen, JourneyShowModal)
        shown = str(app.screen.query_one("#journey-json").render())
        assert json.loads(shown) == BUILTIN["warm-up"].to_dict()      # the same JSON as `journey show`


# ------------------------------------------------------------ open a file
@pytest.mark.asyncio
async def test_open_file_validates_shows_warnings_and_plays(tmp_path):
    path = tmp_path / "mine.json"
    path.write_text(json.dumps({"version": 1, "name": "mine", "stages": [
        {"name": "A", "seconds": 60, "to": {"energy": 3}}]}))      # clamped, with a warning
    app, player = make_app(EditShell())
    async with app.run_test() as pilot:
        await pilot.press("J")
        await pilot.pause(0.1)
        await choose(pilot, "open")
        assert isinstance(app.screen, JourneyFileModal)
        app.screen.query_one("#journey-file", Input).value = str(path)
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, JourneyShowModal)
        assert "clamped" in str(app.screen.query_one("#journey-warnings").render())
        await pilot.click("#play")
        await drive(pilot, player, lambda: player.engine.journey is not None)
        assert player.engine.journey is not None and player.engine.journey.name == "mine"


@pytest.mark.asyncio
async def test_open_file_can_save_instead_of_playing(tmp_path):
    path = tmp_path / "mine.json"
    path.write_text(json.dumps({"version": 1, "name": "mine", "stages": [{"name": "A", "seconds": 60, "to": {}}]}))
    app, player = make_app(EditShell())
    async with app.run_test() as pilot:
        await pilot.press("J")
        await pilot.pause(0.1)
        await choose(pilot, "open")
        app.screen.query_one("#journey-file", Input).value = str(path)
        await pilot.press("enter")
        await pilot.pause(0.2)
        await pilot.click("#save")
        await pilot.pause(0.2)
        app.screen.query_one(Input).value = "From file"
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert JourneyStore().get("From file") is not None
        assert player.engine.journey is None


@pytest.mark.asyncio
async def test_an_invalid_file_is_explained_in_the_dialog(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    app, _ = make_app(EditShell())
    async with app.run_test() as pilot:
        await pilot.press("J")
        await pilot.pause(0.1)
        await choose(pilot, "open")
        app.screen.query_one("#journey-file", Input).value = str(path)
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, JourneyFileModal)
        assert str(app.screen.query_one("#journey-file-status").render()) != ""


@pytest.mark.asyncio
async def test_open_file_only_opens_files_not_journey_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                                     # no file called warm-up here
    app, _ = make_app(EditShell())
    async with app.run_test() as pilot:
        await pilot.press("J")
        await pilot.pause(0.1)
        await choose(pilot, "open")
        app.screen.query_one("#journey-file", Input).value = "warm-up"   # a built-in's name, not a file
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, JourneyFileModal)
        assert "no such file: warm-up" in str(app.screen.query_one("#journey-file-status").render())


def test_the_palette_offers_every_journey_action():
    from gentle_stream.app import StreamApp
    titles = {title for title, _, _ in StreamApp.palette_actions()}
    assert {"Edit the journey", "Save the journey as", "Open a journey file"} <= titles


assert JourneyPickerModal
