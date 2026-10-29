"""PM-045 T6: the live broadcast from the TUI (L): ingest URL, stream key (masked), start and stop, and its state on
the main screen; the key never shows."""
import stat
import sys
from pathlib import Path

import pytest
from textual.widgets import Input

from gentle_stream import broadcast, streamconf
from gentle_stream.app import BroadcastModal, StreamApp
from tests.rtmp_fake import FakeIngest
from tests.test_app import FakeShell, make_app, text

KEY = "SENTINEL-KEY-t6-tui-77rr"
FAKE = str(Path(__file__).with_name("fake_encoder.py"))


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    monkeypatch.delenv(streamconf.KEY_ENV, raising=False)


def fake_encoder(monkeypatch, tmp_path, mode="copy"):
    monkeypatch.setattr(broadcast, "encoder_command",
                        lambda sr: [sys.executable, FAKE, mode, str(tmp_path / "pcm"), "{video_fd}"])


async def open_live(pilot):
    await pilot.press("L")
    await pilot.pause(0.2)
    assert isinstance(pilot.app.screen, BroadcastModal)
    return pilot.app.screen


def status(screen) -> str:
    return str(screen.query_one("#live-status").render())


def screen_text(app) -> str:
    return app.export_screenshot()


async def press(pilot, button: str):
    await pilot.click(f"#{button}")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause(0.3)


@pytest.mark.asyncio
async def test_it_shows_the_url_and_whether_a_key_is_set_never_the_key():
    streamconf.save_url("rtmps://a.rtmps.youtube.com/live2")
    streamconf.save_key(KEY)
    app, _ = make_app(FakeShell())
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_live(pilot)
        assert screen.query_one("#live-url", Input).value == "rtmps://a.rtmps.youtube.com/live2"
        assert f"stream key: set (in {streamconf.key_path()})" in str(screen.query_one("#live-key-state").render())
        assert KEY not in screen_text(app)


@pytest.mark.asyncio
async def test_the_url_is_saved_as_stream_url_does_and_a_bad_one_is_refused():
    app, _ = make_app(FakeShell())
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_live(pilot)
        screen.query_one("#live-url", Input).value = "https://example.com/live"
        await press(pilot, "save-url")
        assert status(screen) == streamconf.BAD_URL and streamconf.load_url() is None
        screen.query_one("#live-url", Input).value = "rtmp://127.0.0.1:1935/live2"
        await press(pilot, "save-url")
        assert status(screen) == "Ingest URL saved: rtmp://127.0.0.1:1935/live2"
        assert streamconf.load_url() == "rtmp://127.0.0.1:1935/live2"


@pytest.mark.asyncio
async def test_the_key_is_typed_masked_saved_0600_and_cleared_from_the_field():
    app, _ = make_app(FakeShell())
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_live(pilot)
        field = screen.query_one("#live-key", Input)
        assert field.password
        field.value = KEY
        assert KEY not in screen_text(app)                       # masked while typed
        await press(pilot, "save-key")
        assert field.value == ""
        assert status(screen) == f"Stream key saved in {streamconf.key_path()} (readable only by you)"
        assert KEY not in screen_text(app)
    path = streamconf.key_path()
    assert path.read_text() == KEY and stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_a_bad_key_is_refused_with_the_clis_message_and_clear_removes_it():
    app, _ = make_app(FakeShell())
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_live(pilot)
        screen.query_one("#live-key", Input).value = "two words"
        await press(pilot, "save-key")
        assert status(screen) == "a stream key is one line of printable characters without spaces, at most 256"
        assert not streamconf.key_path().exists()
        streamconf.save_key(KEY)
        await press(pilot, "clear-key")
        assert status(screen) == f"Stream key removed from {streamconf.key_path()}"
        assert not streamconf.key_path().exists()


@pytest.mark.asyncio
async def test_start_and_stop_broadcast_and_the_main_screen_says_live(monkeypatch, tmp_path):
    ingest = FakeIngest()
    streamconf.save_url(ingest.url)
    streamconf.save_key(KEY)
    fake_encoder(monkeypatch, tmp_path)
    app, player = make_app(FakeShell())
    async with app.run_test(size=(100, 32)) as pilot:
        await open_live(pilot)
        await press(pilot, "start")
        assert not isinstance(app.screen, BroadcastModal)
        assert (player.streaming or {}).get("running")
        await pilot.pause(1.2)
        assert "● LIVE" in text(app, "#state")
        assert f"Broadcasting to {ingest.url}" in text(app, "#status")
        await open_live(pilot)
        await press(pilot, "stop")
        assert player.streaming is None
        await pilot.pause(0.6)
        assert "LIVE" not in text(app, "#state")
        assert f"Broadcast to {ingest.url} ended after 0:0" in text(app, "#status")
        assert KEY not in screen_text(app)
    ingest.wait()


@pytest.mark.asyncio
async def test_a_refused_start_stays_in_the_dialog_with_the_reason(monkeypatch, tmp_path):
    streamconf.save_url("rtmp://127.0.0.1:1/live2")
    fake_encoder(monkeypatch, tmp_path)
    app, player = make_app(FakeShell())
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_live(pilot)
        await press(pilot, "start")
        assert isinstance(app.screen, BroadcastModal) and player.streaming is None
        assert status(screen).startswith("no stream key: run `gentle-stream stream key set`")


@pytest.mark.asyncio
async def test_a_failed_broadcast_shows_on_the_main_screen_and_the_music_plays_on(monkeypatch, tmp_path):
    """S3 in the TUI."""
    monkeypatch.setenv("FAKE_KEY", KEY)
    streamconf.save_url(FakeIngest().url)
    streamconf.save_key(KEY)
    fake_encoder(monkeypatch, tmp_path, "fail")
    app, player = make_app(FakeShell())
    async with app.run_test(size=(100, 32)) as pilot:
        await open_live(pilot)
        await press(pilot, "start")
        await pilot.pause(1.5)
        state = text(app, "#state")
        assert "LIVE failed" in state and "Playing" in state
        assert KEY not in screen_text(app)
        player.stream_stop()


@pytest.mark.asyncio
async def test_everything_fits_in_80_by_24():
    app, _ = make_app(FakeShell())
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_live(pilot)
        for name in ("live-url", "save-url", "live-key-state", "live-key", "save-key", "clear-key", "start",
                     "cancel", "live-status"):
            region = screen.query_one(f"#{name}").region
            assert region.width > 0 and region.right <= 80 and region.bottom <= 24, name


def test_the_palette_offers_the_live_broadcast():
    assert "Live broadcast" in {title for title, _, _ in StreamApp.palette_actions()}
