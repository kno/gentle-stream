"""PM-042: say a phrase from the TUI, choosing voice, rate and effect (fake text-to-speech, never the real one)."""
import pytest
from textual.widgets import Input, Select

from gentle_stream import speech
from gentle_stream.app import SayModal, StreamApp
from tests.test_app import FakeShell, make_app, text
from tests.test_speech_voices import FAKE, argv


@pytest.fixture
def tts(tmp_path, monkeypatch):
    """Fake `say`/`espeak-ng` on a private PATH (the same fake as tests/test_speech_voices.py)."""
    import sys

    bin_dir, log = tmp_path / "bin", tmp_path / "tts.log"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    speech.clear_cache()

    def install(*names):
        for name in names:
            path = bin_dir / name
            path.write_text(FAKE.format(python=sys.executable, log=str(log)))
            path.chmod(0o755)
        return log

    yield install
    speech.clear_cache()


async def open_say(pilot):
    await pilot.press("t")
    await pilot.pause(0.1)
    assert isinstance(pilot.app.screen, SayModal)
    await pilot.app.workers.wait_for_complete()            # the voice list (the fake program starts slowly)
    await pilot.pause(0.1)
    return pilot.app.screen


async def say(pilot, screen):
    await pilot.click("#say")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause(0.2)


@pytest.mark.asyncio
async def test_the_voice_list_comes_from_the_system(tts):
    tts("say")
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_say(pilot)
        select = screen.query_one("#say-voice", Select)
        assert [value for _, value in select._options] == ["", "Samantha", "Bad News", "Paulina"]
        assert select.value == ""                                     # the default voice


@pytest.mark.asyncio
async def test_say_sends_the_options_of_ctl_say_and_queues_the_phrase(tts):
    log = tts("say")
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_say(pilot)
        screen.query_one("#say-text", Input).value = "Almost there"
        screen.query_one("#say-voice", Select).value = "Samantha"
        screen.query_one("#say-rate", Input).value = "180"
        screen.query_one("#say-effect", Select).value = "space"
        await say(pilot, screen)
        assert not isinstance(app.screen, SayModal)
        assert argv(log)[0][3:] == ["--data-format=LEI16@22050", "-v", "Samantha", "-r", "180"]   # as `ctl say`
        assert len(player.engine._speech_queue) == 1
        assert "Almost there" in text(app, "#status")


@pytest.mark.asyncio
async def test_without_a_backend_the_dialog_says_so_and_nothing_is_queued(tts):
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_say(pilot)
        assert speech.NO_BACKEND in str(screen.query_one("#say-status").render())
        screen.query_one("#say-text", Input).value = "Hello"
        await say(pilot, screen)
        assert isinstance(app.screen, SayModal)
        assert speech.NO_BACKEND in str(screen.query_one("#say-status").render())
        assert player.engine._speech_queue == []


@pytest.mark.asyncio
@pytest.mark.parametrize("phrase, rate, message", [
    ("", "", "a phrase must have between 1 and 200 characters"),
    ("Hi", "fast", "rate must be a whole number from 80 to 400"),
    ("Hi", "500", "rate must be a whole number from 80 to 400"),
])
async def test_invalid_input_stays_in_the_dialog(tts, phrase, rate, message):
    log = tts("say")
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_say(pilot)
        screen.query_one("#say-text", Input).value = phrase
        screen.query_one("#say-rate", Input).value = rate
        await say(pilot, screen)
        assert isinstance(app.screen, SayModal)
        assert message in str(screen.query_one("#say-status").render())
        assert not log.exists() and player.engine._speech_queue == []


def test_the_local_player_says_like_the_background_player(tts):
    from gentle_stream.engine import Engine
    from gentle_stream.player import Player
    from gentle_stream.style import Style
    from tests.test_player import FakeStream

    log = tts("say")
    player = Player(Engine(Style(), seed=1, samples=False), stream_factory=FakeStream)
    assert player.say("Hi", voice="Nobody", rate=200, effect="radio") == [
        'unknown voice "Nobody"; using the default voice (see gentle-stream ctl say --list-voices)']
    assert argv(log)[0][3:] == ["--data-format=LEI16@22050", "-r", "200"]
    assert len(player.engine._speech_queue) == 1


def test_the_palette_offers_say():
    assert "Say a phrase" in {title for title, _, _ in StreamApp.palette_actions()}
