import threading

import pytest

from gentle_stream.app import ModelPicker, PresetPicker, SaveDialog, StreamApp, format_time
from gentle_stream.bridge import InterpretError, Usage
from gentle_stream.engine import Engine
from gentle_stream.journey import JourneySnapshot
from gentle_stream.player import NowPlaying, Player
from gentle_stream.presets import PresetStore
from gentle_stream.style import Style
from tests.test_daemon import runtime, wait_for  # noqa: F401  (fixture: private runtime dir, fake audio, cleanup)
from tests.test_player import FakeStream


class FakeShell:
    def __init__(self, answer=None, error=None, models=("claude-bridge/claude-haiku-5-5", "openai-codex/gpt-6-luna"),
                 usage=None):
        self.answer, self.error, self.models, self.usage = answer, error, list(models), usage
        self.model = None
        self.calls = []
        self.release = threading.Event()
        self.release.set()

    def interpret(self, mood, current):
        self.calls.append((mood, current))
        self.release.wait(5)
        if self.error:
            raise InterpretError(self.error)
        return Style.from_dict({**self.answer, "mood": mood}, current)

    def interpret_with_usage(self, mood, current):
        return self.interpret(mood, current), self.usage

    def list_models(self):
        return self.models

    def cancel(self):
        pass


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    """No test may touch the real ~/.config, even through the default preset store."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def make_app(shell, **kw):
    player = Player(Engine(Style(name="Midnight Rain"), seed=1), stream_factory=lambda **k: FakeStream(**k),
                    prebuffer=0.3)
    return StreamApp(player, shell, **kw), player


def text(app, selector):
    return str(app.query_one(selector).render())


@pytest.mark.asyncio
async def test_shows_what_is_playing_and_the_controls():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        assert "Midnight Rain" in text(app, "#title")
        assert "D minor" in text(app, "#details")
        assert "Playing" in text(app, "#state")
        assert "0:00 · -" in text(app, "#state")      # elapsed · cycle remaining, right at the start
    assert not player._producer.is_alive()        # quitting closes the audio


@pytest.mark.parametrize("seconds,expected", [(0, "0:00"), (59, "0:59"), (60, "1:00"), (125, "2:05"), (-1, "0:00")])
def test_format_time_renders_minutes_and_seconds(seconds, expected):
    assert format_time(seconds) == expected


@pytest.mark.asyncio
async def test_space_pauses_and_resumes():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.press("space")
        assert not player.playing
        await pilot.pause(0.1)
        assert "Paused" in text(app, "#state")
        await pilot.press("space")
        assert player.playing


@pytest.mark.asyncio
async def test_n_starts_the_next_piece():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        await pilot.press("n")
        await pilot.pause(0.2)
        assert player.engine.piece == 2 or player.engine._pending_next


@pytest.mark.asyncio
async def test_a_mood_is_interpreted_and_queued():
    shell = FakeShell(answer={"name": "Summer Storm", "mode": "mixolydian", "bpm": 78})
    app, player = make_app(shell)
    async with app.run_test() as pilot:
        await pilot.press("slash")
        await pilot.press(*"summer storm")
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert shell.calls[0][0] == "summer storm"
        assert "Summer Storm" in text(app, "#status")
        queued = player.engine._pending_style or player.engine.style
        assert (queued.name, queued.mode, queued.mood) == ("Summer Storm", "mixolydian", "summer storm")
        assert app.query_one("#mood").value == ""


@pytest.mark.asyncio
async def test_the_status_says_which_model_is_interpreting():
    shell = FakeShell(answer={"name": "x"})
    shell.model = "openai-codex/gpt-6-luna"
    shell.release.clear()
    app, _ = make_app(shell)
    async with app.run_test() as pilot:
        await pilot.press("slash", *"calm", "enter")
        await pilot.pause(0.1)
        assert "openai-codex/gpt-6-luna" in text(app, "#status")
        shell.release.set()
        await app.workers.wait_for_complete()


@pytest.mark.asyncio
async def test_an_interpretation_error_is_shown_and_the_music_keeps_playing():
    app, player = make_app(FakeShell(error='Model "nope" not found.'))
    async with app.run_test() as pilot:
        await pilot.press("slash", *"x", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert 'Model "nope" not found.' in text(app, "#status")
        assert player.playing and player.engine.style.name == "Midnight Rain"


@pytest.mark.asyncio
async def test_escape_leaves_the_mood_input_so_keys_control_playback():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.press("slash")
        await pilot.press("space")                 # typed into the input
        assert player.playing
        await pilot.press("escape", "space")
        assert not player.playing


@pytest.mark.asyncio
async def test_m_picks_the_model_gentle_shell_uses():
    shell = FakeShell()
    app, _ = make_app(shell)
    async with app.run_test() as pilot:
        await pilot.press("m")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ModelPicker)
        await pilot.press("down", "down", "enter")   # default, haiku, gpt-6-luna
        await pilot.pause(0.1)
        assert shell.model == "openai-codex/gpt-6-luna"
        assert "openai-codex/gpt-6-luna" in text(app, "#model")


@pytest.mark.asyncio
async def test_plus_and_minus_change_the_volume_in_steps_of_5():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        assert player.volume == pytest.approx(0.8)
        await pilot.press("minus")
        assert player.volume == pytest.approx(0.75)
        await pilot.pause(0.1)
        assert "vol 75%" in text(app, "#state")
        await pilot.press("plus", "plus")
        assert player.volume == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_up_and_down_change_the_volume_in_steps_of_1():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.press("down")
        assert player.volume == pytest.approx(0.79)
        await pilot.pause(0.1)
        assert "vol 79%" in text(app, "#state")
        await pilot.press("up", "up")
        assert player.volume == pytest.approx(0.81)


@pytest.mark.asyncio
async def test_volume_steps_stop_at_0_and_100_percent():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        player.set_volume(0.03)
        await pilot.press("minus")
        assert player.volume == 0.0
        player.set_volume(0.98)
        await pilot.press("plus")
        assert player.volume == 1.0
        await pilot.press("down")
        assert player.volume == pytest.approx(0.99)


@pytest.mark.asyncio
async def test_an_initial_mood_is_interpreted_on_start():
    shell = FakeShell(answer={"name": "Opening"})
    app, _ = make_app(shell, initial_mood="foggy harbour")
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert shell.calls[0][0] == "foggy harbour"


@pytest.mark.asyncio
async def test_the_app_uses_the_gentleman_programming_theme():
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        assert app.theme == "gentleman"
        theme = app.current_theme
        assert (theme.primary, theme.background, theme.error) == ("#ff76c3", "#140a12", "#ff718f")
        assert app.query_one("#title").styles.color.hex.lower() == "#ff76c3"


@pytest.mark.asyncio
async def test_quitting_during_an_interpretation_cancels_it_right_away():
    import time

    shell = FakeShell(answer={"name": "Late"})
    shell.release.clear()
    shell.cancel = shell.release.set            # cancelling unblocks the in-flight call
    app, player = make_app(shell)
    async with app.run_test() as pilot:
        await pilot.press("slash", *"rain", "enter")
        await pilot.pause(0.1)
        t0 = time.monotonic()
    assert time.monotonic() - t0 < 2
    assert shell.release.is_set()


@pytest.mark.asyncio
async def test_an_error_with_brackets_is_shown_literally():
    app, _ = make_app(FakeShell(error="bad [model] id"))
    async with app.run_test() as pilot:
        await pilot.press("slash", *"x", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert "bad [model] id" in text(app, "#status")


# ------------------------------------------------------------ token usage
CALL = Usage(input=17000, output=700, cache_write=16000, total=17700, cost_usd=0.00075)


@pytest.mark.asyncio
async def test_each_interpretation_shows_its_usage_and_the_session_total_adds_up():
    shell = FakeShell(answer={"name": "Summer Storm"}, usage=CALL)
    shell.model = "openai-codex/gpt-6-luna"
    app, _ = make_app(shell)
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        assert "session" not in text(app, "#model")       # nothing spent yet
        await pilot.press("slash", *"storm", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        status = text(app, "#status")
        assert "Up next: Summer Storm" in status and "17.7k tokens · $0.0008" in status
        assert text(app, "#model") == "model: openai-codex/gpt-6-luna · session: 17.7k tokens · $0.0008"
        await pilot.press("slash", *"again", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert "session: 35.4k tokens · $0.0015" in text(app, "#model")


@pytest.mark.asyncio
async def test_unknown_usage_shows_the_style_and_adds_nothing():
    app, _ = make_app(FakeShell(answer={"name": "Old Shell"}))
    async with app.run_test() as pilot:
        await pilot.press("slash", *"x", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert "Up next: Old Shell" in text(app, "#status") and "tokens" not in text(app, "#status")
        assert "session" not in text(app, "#model")


@pytest.mark.asyncio
async def test_a_failed_interpretation_adds_nothing_to_the_session(store):
    shell = FakeShell(answer={"name": "Ok"}, usage=CALL)
    app, _ = make_app(shell, presets=store)
    async with app.run_test() as pilot:
        await pilot.press("slash", *"ok", "enter")
        await app.workers.wait_for_complete()
        shell.error = "boom"
        await pilot.press("slash", *"bad", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert "boom" in text(app, "#status")
        assert "session: 17.7k tokens · $0.0008" in text(app, "#model")
        store.save("Rain", RAIN)
        await pilot.press("p", "enter")                  # applying a saved prompt is free
        await pilot.pause(0.1)
        assert "session: 17.7k tokens · $0.0008" in text(app, "#model")


# ------------------------------------------------------------ saved prompts
RAIN = Style(name="Rainy Café", mood="rainy night in a small café", key="F", mode="dorian", bpm=81.0,
             progression=(1, 4, 1, 4), chords="rhodes", lead="nylon", drums="soft")


@pytest.fixture
def store(tmp_path):
    return PresetStore(tmp_path / "presets.json")


@pytest.mark.asyncio
async def test_s_saves_the_audible_style_under_a_typed_name(store):
    app, player = make_app(FakeShell(), presets=store)
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        audible = player.now.style
        await pilot.press("s")
        await pilot.pause(0.1)
        assert isinstance(app.screen, SaveDialog)
        field = app.screen.query_one("Input")
        assert field.value == audible.name               # prefilled with the style name
        field.value = ""
        await pilot.press(*"late night", "enter")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, SaveDialog)
        assert "Saved “late night”" in text(app, "#status")
        preset = store.get("late night")
        assert preset.style.to_dict() == {**audible.to_dict(), "name": "late night"}
        assert preset.mood == audible.mood
        assert app.query_one("#mood").value == ""        # the dialog's Enter is not a mood request


@pytest.mark.asyncio
async def test_saving_an_existing_name_says_it_replaced_it(store):
    store.save("Late Night", RAIN)
    app, _ = make_app(FakeShell(), presets=store)
    async with app.run_test() as pilot:
        await pilot.press("s")
        await pilot.pause(0.1)
        app.screen.query_one("Input").value = "late night"
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert "Replaced “late night”" in text(app, "#status")
        assert [p.name for p in store.list()] == ["late night"]


@pytest.mark.asyncio
async def test_an_empty_name_is_rejected(store):
    shell = FakeShell()
    app, _ = make_app(shell, presets=store)
    async with app.run_test() as pilot:
        await pilot.press("s")
        await pilot.pause(0.1)
        app.screen.query_one("Input").value = "   "
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert isinstance(app.screen, SaveDialog)
        assert "empty" in text(app.screen, "#save-status").lower()
        assert store.list() == [] and shell.calls == []


@pytest.mark.asyncio
async def test_escape_cancels_the_save_dialog(store):
    app, player = make_app(FakeShell(), presets=store)
    async with app.run_test() as pilot:
        await pilot.press("s")
        await pilot.pause(0.1)
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, SaveDialog)
        assert store.list() == []
        await pilot.press("space")                     # keys control playback again
        assert not player.playing


@pytest.mark.asyncio
async def test_p_applies_a_saved_prompt_instantly_without_gentle_shell(store):
    store.save("Archive", Style(mood="old tapes"))
    saved, _ = store.save("Rainy Café", RAIN)
    shell = FakeShell(answer={"name": "unused"})
    app, player = make_app(shell, presets=store)
    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause(0.1)
        assert isinstance(app.screen, PresetPicker)
        listed = str(app.screen.query_one("OptionList").get_option_at_index(1).prompt)
        assert "Rainy Café" in listed and "rainy night in a small café" in listed
        await pilot.press("down", "enter")             # Archive, Rainy Café
        await pilot.pause(0.1)
        assert not isinstance(app.screen, PresetPicker)
        assert shell.calls == []
        queued = player.engine._pending_style or player.engine.style
        assert queued == saved.style
        assert (queued.name, queued.mood) == ("Rainy Café", "rainy night in a small café")
        assert "Up next: Rainy Café (saved)" in text(app, "#status")


@pytest.mark.asyncio
async def test_d_deletes_the_highlighted_preset(store):
    store.save("Archive", Style())
    store.save("Rainy Café", RAIN)
    app, _ = make_app(FakeShell(), presets=store)
    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause(0.1)
        await pilot.press("d")
        await pilot.pause(0.1)
        assert [p.name for p in store.list()] == ["Rainy Café"]
        assert app.screen.query_one("OptionList").option_count == 1
        await pilot.press("delete")
        await pilot.pause(0.1)
        assert store.list() == []
        assert "No saved prompts yet" in text(app.screen, "#presets-status")


@pytest.mark.asyncio
async def test_an_empty_store_shows_a_hint_and_escape_closes_the_presets(store):
    app, player = make_app(FakeShell(), presets=store)
    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause(0.1)
        assert "No saved prompts yet" in text(app.screen, "#presets-status")
        await pilot.press("enter")
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, PresetPicker)
        assert player.engine._pending_style is None


@pytest.mark.asyncio
async def test_a_corrupt_presets_file_is_reported_in_the_picker(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text("{oops", encoding="utf-8")
    app, _ = make_app(FakeShell(), presets=PresetStore(path))
    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause(0.1)
        assert "presets.json" in text(app.screen, "#presets-status")
    assert path.read_text(encoding="utf-8") == "{oops"


# ------------------------------------------------------------ background player
@pytest.mark.asyncio
async def test_b_leaves_the_music_playing_in_the_background(runtime):
    from gentle_stream import client

    player = client.ensure()
    app = StreamApp(player, FakeShell())
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        assert "Playing" in text(app, "#state")
        await pilot.press("b")
    still = client.connect()
    assert still.pid == player.pid and still.playing


@pytest.mark.asyncio
async def test_q_quits_and_stops_the_background_music(runtime):
    from gentle_stream import client

    player = client.ensure()
    app = StreamApp(player, FakeShell())
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        await pilot.press("q")
    with pytest.raises(client.NoPlayer):
        client.connect()


@pytest.mark.asyncio
async def test_an_attached_tui_shows_and_controls_the_running_music(runtime):
    from gentle_stream import client

    other = client.ensure()
    other.set_style(RAIN)
    wait_for(lambda: other.spectrum(8) is not None and other.now.style == RAIN, timeout=20)
    shell = FakeShell(answer={"name": "Summer Storm", "mode": "mixolydian"})
    app = StreamApp(client.ensure(), shell)
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        assert "Rainy Café" in text(app, "#title")
        assert "rainy night in a small café" in text(app, "#mood-line")
        await pilot.press("space")
        await pilot.pause(0.2)
        assert "Paused" in text(app, "#state")
        other.spectrum(8)
        assert not other.playing
        await pilot.press("minus")
        assert other.spectrum(8) is not None and other.volume == pytest.approx(0.75)
        await pilot.press("space")                     # playing again, so the next bars get rendered
        await pilot.press("slash", *"storm", "enter")
        await app.workers.wait_for_complete()
        assert shell.calls[0][1] == RAIN               # interpreted from what the player renders
        wait_for(lambda: other.spectrum(8) is not None and other.style.name == "Summer Storm")
        assert other.style.mode == "mixolydian"
        await pilot.press("b")


@pytest.mark.asyncio
async def test_the_tui_leaves_when_the_music_is_stopped_elsewhere(runtime):
    from gentle_stream import client

    app = StreamApp(client.ensure(), FakeShell())
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        client.connect().close()                       # e.g. `gentle-stream ctl stop` from another terminal
        await pilot.pause(0.3)
        assert not app.is_running


@pytest.mark.asyncio
async def test_b_with_an_in_process_player_closes_it():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("b")
    assert not player._producer.is_alive()            # nothing can outlive the app in-process


@pytest.mark.asyncio
async def test_the_footer_shows_back_and_quit():
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        keys = {b.key: b.description for b in app.BINDINGS if b.show}
        assert "b" in keys and "q" in keys
        assert "keep" in keys["b"].lower() and "stop" in keys["q"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("size, min_rows", [((160, 45), 20), ((80, 24), 5)])
async def test_the_spectrum_fills_the_free_height_and_the_info_sits_by_the_input(size, min_rows):
    app, _ = make_app(FakeShell())
    async with app.run_test(size=size) as pilot:
        await pilot.pause(0.3)
        spectrum = app.query_one("#spectrum")
        assert spectrum.region.height >= min_rows
        assert len(str(spectrum.render()).split("\n")) == spectrum.region.height
        status, mood = app.query_one("#status"), app.query_one("#mood")
        gap = mood.region.y - (status.region.y + status.region.height)
        assert 0 <= gap <= 3                      # no empty band between the info and the input


# ------------------------------------------------------------ journey progress
def show_journey(player, snapshot):
    """Make `snapshot` the journey of the audible bar (nothing pulls the fake stream, so it stays)."""
    player.now = NowPlaying(player.now.style, player.now.piece, 5, 0.0, snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize("downs, method", [(0, "journey_restart"), (1, "journey_skip"), (2, "journey_stop")],
                         ids=["restart", "skip", "stop"])
async def test_pm008_j_opens_the_journey_menu_and_each_entry_reaches_the_player(downs, method):
    from gentle_stream.app import JourneyMenu

    app, player = make_app(FakeShell())
    calls = []
    for name in ("journey_restart", "journey_skip", "journey_stop"):
        setattr(player, name, lambda name=name: calls.append(name))
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.pause(0.1)
        assert isinstance(app.screen, JourneyMenu)
        for _ in range(downs):
            await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, JourneyMenu) and calls == [method]


@pytest.mark.asyncio
async def test_pm008_journey_menu_escape_does_nothing_and_errors_show_in_the_status():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.press("j", "escape")
        await pilot.pause(0.1)
        assert "Press / to describe a mood." in text(app, "#status")
        await pilot.press("j", "down", "enter")             # skip, but no journey runs in this player
        await pilot.pause(0.1)
        assert "no journey is running" in text(app, "#status")


@pytest.mark.asyncio
async def test_no_journey_leaves_the_journey_line_empty_and_hidden():
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        assert text(app, "#journey") == "" and not app.query_one("#journey").display


@pytest.mark.asyncio
async def test_the_journey_line_shows_stage_progress_tempo_and_time_left():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        show_journey(player, JourneySnapshot("warm-up", "Warm-up", 2, 3, "Rise", 0.62, 84.0, 100.0, 400.0))
        await pilot.pause(0.2)
        assert text(app, "#journey") == 'Journey: Warm-up · stage 2/3 "Rise" · 62% · 84 → 100 bpm · 6:40 left'
        assert app.query_one("#journey").display


@pytest.mark.asyncio
async def test_a_sustaining_journey_says_so_instead_of_the_time_left():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        show_journey(player, JourneySnapshot("warm-up", "Warm-up", 4, 4, "Glow", 1.0, 100.0, 100.0, None))
        await pilot.pause(0.2)
        assert text(app, "#journey") == 'Journey: Warm-up · stage 4/4 "Glow" · 100% · 100 bpm · sustaining'


@pytest.mark.asyncio
async def test_a_journey_line_shows_markup_in_names_literally_and_hides_again_when_it_ends():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        show_journey(player, JourneySnapshot("x", "[b]Bold", 1, 1, "[i]Lean", 0.5, 70.0, 70.0, 61.0))
        await pilot.pause(0.2)
        assert text(app, "#journey") == 'Journey: [b]Bold · stage 1/1 "[i]Lean" · 50% · 70 bpm · 1:01 left'
        show_journey(player, None)
        await pilot.pause(0.2)
        assert text(app, "#journey") == "" and not app.query_one("#journey").display


# ------------------------------------------------------------ PM-012: journey prompt and picker
def valid_journey(name="night-drive"):
    from gentle_stream.journey import BUILTIN
    return {**BUILTIN["warm-up"].to_dict(), "name": name, "title": "Night drive"}


class JourneyShell(FakeShell):
    def __init__(self, journey=None, error=None, **kw):
        super().__init__(**kw)
        self.journey, self.journey_error, self.prompts = journey, error, []

    def journey_from_prompt(self, description):
        from gentle_stream.bridge import InterpretError
        from gentle_stream.journey import Journey
        self.prompts.append(description)
        if self.journey_error:
            raise self.journey_error
        if isinstance(self.journey, dict) and self.journey.get("version") != 1:
            raise InterpretError('invalid journey: "version" must be 1')
        return Journey.from_dict(self.journey), self.usage


def picker_ids(app):
    from textual.widgets import OptionList
    options = app.screen.query_one(OptionList)
    return [options.get_option_at_index(i).id for i in range(options.option_count)]


def record_journey_start(player):
    started = []
    player.journey_start = started.append
    return started


@pytest.mark.asyncio
async def test_pm012_shift_j_lists_create_then_builtins_then_saved_alphabetically():
    from gentle_stream.app import JourneyPickerModal
    from gentle_stream.journey import BUILTIN, Journey, JourneyStore

    store = JourneyStore()
    for name in ("zeta", "alpha"):
        store.save(name, Journey.from_dict(valid_journey(name)))
    app, _ = make_app(JourneyShell())
    async with app.run_test() as pilot:
        await pilot.press("J")
        await pilot.pause(0.1)
        assert isinstance(app.screen, JourneyPickerModal)
        assert picker_ids(app) == (["create"] + [f"builtin:{n}" for n in BUILTIN] + ["saved:alpha", "saved:zeta"])


@pytest.mark.asyncio
async def test_pm012_picking_a_builtin_or_saved_journey_starts_it_immediately():
    from gentle_stream.journey import BUILTIN, Journey, JourneyStore

    JourneyStore().save("alpha", Journey.from_dict(valid_journey("alpha")))
    app, player = make_app(JourneyShell())
    started = record_journey_start(player)
    async with app.run_test() as pilot:
        await pilot.press("J", "down", "enter")          # first built-in
        await pilot.pause(0.1)
        await pilot.press("J", *["down"] * (len(BUILTIN) + 1), "enter")   # first saved
        await pilot.pause(0.1)
        assert "Journey alpha" in text(app, "#status")
    first = next(iter(BUILTIN.values()))
    assert started == [first.to_dict(), JourneyStore().get("alpha").to_dict()]


@pytest.mark.asyncio
async def test_pm012_create_saves_the_generated_journey_and_reopens_the_picker_on_it():
    from gentle_stream.app import JourneyPickerModal, JourneyPromptModal
    from gentle_stream.journey import Journey, JourneyStore

    shell = JourneyShell(journey=valid_journey("night-drive"))
    app, player = make_app(shell)
    started = record_journey_start(player)
    async with app.run_test() as pilot:
        await pilot.press("J", "enter")                  # "Create from a description…"
        await pilot.pause(0.1)
        assert isinstance(app.screen, JourneyPromptModal)
        await pilot.press(*"slow night drive", "enter")
        await pilot.pause(0.3)
        assert shell.prompts == ["slow night drive"]
        assert isinstance(app.screen, JourneyPickerModal)
        assert picker_ids(app)[app.screen.query_one("OptionList").highlighted] == "saved:night-drive"
        await pilot.press("enter")
        await pilot.pause(0.1)
    saved = JourneyStore().get("night-drive")
    expected = Journey.from_dict({**valid_journey("night-drive"), "title": "night-drive"}, name="night-drive")
    assert saved == expected
    assert started == [saved.to_dict()]


@pytest.mark.asyncio
async def test_pm012_typed_name_wins_and_builtin_generated_name_stays_open():
    from gentle_stream.app import JourneyPickerModal, JourneyPromptModal
    from gentle_stream.journey import JourneyStore

    shell = JourneyShell(journey=valid_journey("warm-up"))
    app, _ = make_app(shell)
    async with app.run_test() as pilot:
        await pilot.press("J", "enter")
        await pilot.pause(0.1)
        await pilot.press(*"first", "tab", *"My Drive!", "enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, JourneyPickerModal)
        assert JourneyStore().get("My Drive!") is not None
        await pilot.press("escape", "J", "enter")
        await pilot.pause(0.1)
        await pilot.press(*"second", "enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, JourneyPromptModal)
        assert app.screen.query_one("#prompt").value == "second"
        assert "built-in" in str(app.screen.query_one("#journey-error").render())
    assert JourneyStore().get("warm-up") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("error, message", [
    (InterpretError("gentle-shell timed out"), "gentle-shell timed out"),
    (InterpretError("no JSON object in the answer"), "no JSON object in the answer"),
    (None, '"version" must be 1'),
], ids=["timeout", "invalid-json", "schema"])
async def test_pm012_errors_show_in_the_modal_and_keep_the_input(error, message):
    from textual.widgets import Input
    from gentle_stream.app import JourneyPromptModal
    from gentle_stream.journey import JourneyStore

    shell = JourneyShell(journey={"version": 2, "stages": []}, error=error)
    app, player = make_app(shell)
    started = record_journey_start(player)
    async with app.run_test() as pilot:
        await pilot.press("J", "enter")
        await pilot.pause(0.1)
        await pilot.press(*"rainy dawn", "enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, JourneyPromptModal)
        assert app.screen.query_one("#prompt", Input).value == "rainy dawn"
        assert message in str(app.screen.query_one("#journey-error").render())
    assert JourneyStore().list() == [] and started == []


@pytest.mark.asyncio
async def test_pm012_escape_dismisses_both_modals_without_saving_or_playing():
    from gentle_stream.app import JourneyPickerModal, JourneyPromptModal
    from gentle_stream.journey import JourneyStore

    shell = JourneyShell(journey=valid_journey())
    app, player = make_app(shell)
    started = record_journey_start(player)
    async with app.run_test() as pilot:
        await pilot.press("J")
        await pilot.pause(0.1)
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, JourneyPickerModal)
        await pilot.press("J", "enter")
        await pilot.pause(0.1)
        await pilot.press(*"draft", "escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, (JourneyPickerModal, JourneyPromptModal))
        assert "Press / to describe a mood." in text(app, "#status")
    assert shell.prompts == [] and JourneyStore().list() == [] and started == []


@pytest.mark.asyncio
async def test_pm012_lowercase_j_still_opens_the_journey_controls_and_escape_closes_them():
    from gentle_stream.app import JourneyMenu

    app, _ = make_app(JourneyShell())
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.pause(0.1)
        assert isinstance(app.screen, JourneyMenu)
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, JourneyMenu)


def test_pm012_in_process_player_starts_a_journey_object():
    from gentle_stream.journey import BUILTIN

    player = Player(Engine(Style(name="Midnight Rain"), seed=1), stream_factory=lambda **k: FakeStream(**k))
    queued = []
    player.engine.queue_journey = queued.append
    player.journey_start(BUILTIN["warm-up"].to_dict())
    assert queued == [BUILTIN["warm-up"]]


# ------------------------------------------------------------ PM-014: binaural status line
@pytest.mark.parametrize("setting, line", [
    (None, ""),
    ((200, 6, 0.05), "Binaural: 200 Hz carrier · 6 Hz beat · 5% · headphones recommended"),
    ((432.5, 7.5, 0.045), "Binaural: 432.5 Hz carrier · 7.5 Hz beat · 4.5% · headphones recommended"),
], ids=["off", "defaults", "fractions"])
def test_pm014_binaural_line(setting, line):
    from gentle_stream.app import binaural_line
    from gentle_stream.binaural import Binaural

    assert binaural_line(Binaural(*setting) if setting else None) == line


@pytest.mark.asyncio
async def test_pm014_the_binaural_line_appears_only_while_it_is_on():
    from gentle_stream.binaural import Binaural

    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        assert text(app, "#binaural") == "" and not app.query_one("#binaural").display
        player.engine.queue_binaural(Binaural(200, 6, 0.05))
        await pilot.pause(0.2)
        assert text(app, "#binaural") == "Binaural: 200 Hz carrier · 6 Hz beat · 5% · headphones recommended"
        assert app.query_one("#binaural").display
        player.engine.queue_binaural(None)
        await pilot.pause(0.2)
        assert text(app, "#binaural") == "" and not app.query_one("#binaural").display
