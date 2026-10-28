"""PM-043: voice packs and the downloads from the TUI (v), leaving the store and caches as the CLI does.

The downloads are local fakes (a .7z and a .deb built here); nothing reaches the network.
"""
import threading
from pathlib import Path

import pytest
from textual.widgets import Button, Input, OptionList, ProgressBar

from gentle_stream import main, samples, voicepacks, voicesetup
from gentle_stream.app import StreamApp, VoicesModal
from tests.test_app import FakeShell, make_app
from tests.test_samples import SF2, make_deb
from tests.test_setup_voices import make_archive, needs_bsdtar
from tests.test_voicepacks import MANIFEST, make_pack

CHOIR = "freepats-synth-choir"


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    """Private config and cache dirs (A); a test that compares with the CLI switches to B with `use`."""
    def use(name):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / name / "config"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / name / "cache"))
        return tmp_path / name

    use("A")
    return use


def tree(root: Path) -> dict[str, bytes]:
    """Every file under `root` by relative path, with `root` itself replaced in the bytes (voices.json holds it)."""
    return {str(p.relative_to(root)): p.read_bytes().replace(str(root).encode(), b"<root>")
            for p in sorted(root.rglob("*")) if p.is_file()}


def cli(capsys, *args) -> tuple[int, list[str], str]:
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out.splitlines(), err


async def open_voices(pilot):
    await pilot.press("v")
    await pilot.pause(0.1)
    assert isinstance(pilot.app.screen, VoicesModal)
    return pilot.app.screen


def shown(screen) -> list[str]:
    options = screen.query_one("#voices-list", OptionList)
    return [str(options.get_option_at_index(i).prompt) for i in range(options.option_count)]


def status(screen) -> str:
    return str(screen.query_one("#voices-status").render())


async def press(pilot, button: str):
    await pilot.click(f"#{button}")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause(0.2)


# ------------------------------------------------------------ voice packs
@pytest.mark.asyncio
async def test_the_list_is_the_one_voices_list_prints(tmp_path, capsys):
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_voices(pilot)
        lines = shown(screen)
    assert lines == cli(capsys, "voices", "list")[1] == ["No voice packs. Add one with: gentle-stream voices add FOLDER"]
    store = voicepacks.VoiceStore()
    store.add(make_pack(tmp_path / "one", {**MANIFEST, "name": "One"}))
    store.add(make_pack(tmp_path / "two", {**MANIFEST, "name": "Two"}))
    (tmp_path / "one" / "pack.json").unlink()                         # one that no longer loads
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_voices(pilot)
        on_screen = shown(screen)
    lines = cli(capsys, "voices", "list")[1]       # outside the app: it holds stdout while it runs
    assert on_screen == lines and len(lines) == 2
    assert lines[0].startswith("  One · unavailable:") and lines[1].startswith("* Two · license: CC0-1.0")


@pytest.mark.asyncio
async def test_add_leaves_the_store_as_voices_add_does(tmp_path, capsys, dirs):
    folder = make_pack(tmp_path / "pack")
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_voices(pilot)
        screen.query_one("#voices-folder", Input).value = str(folder)
        await press(pilot, "add")
        assert status(screen) == 'Added voice pack "Test Choir" (CC0-1.0); the choir now sings it'
        on_screen = shown(screen)
    assert on_screen == cli(capsys, "voices", "list")[1]
    by_tui = voicepacks.default_path().read_bytes()
    dirs("B")
    assert cli(capsys, "voices", "add", str(folder))[0] == 0
    assert voicepacks.default_path().read_bytes() == by_tui


@pytest.mark.asyncio
async def test_a_pack_the_cli_refuses_is_refused_with_its_message_and_nothing_is_written(tmp_path, capsys):
    folder = make_pack(tmp_path / "pack", {k: v for k, v in MANIFEST.items() if k != "license"})
    code, _, err = cli(capsys, "voices", "add", str(folder))
    assert code == 1
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_voices(pilot)
        screen.query_one("#voices-folder", Input).value = str(folder)
        await press(pilot, "add")
        assert status(screen) == err.strip().removeprefix("gentle-stream: ")
    assert not voicepacks.default_path().exists()


@pytest.mark.asyncio
async def test_remove_takes_the_highlighted_pack_as_voices_remove_does(tmp_path, capsys, dirs):
    for name in ("One", "Two"):
        voicepacks.VoiceStore().add(make_pack(tmp_path / name, {**MANIFEST, "name": name}))
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_voices(pilot)
        screen.query_one("#voices-list", OptionList).highlighted = 1
        await press(pilot, "remove")
        assert status(screen) == 'Removed voice pack "Two"'
        on_screen = shown(screen)
    assert on_screen == cli(capsys, "voices", "list")[1]
    by_tui = voicepacks.default_path().read_bytes()
    dirs("B")
    for name in ("One", "Two"):
        voicepacks.VoiceStore().add(tmp_path / name)
    assert cli(capsys, "voices", "remove", "Two")[0] == 0
    assert voicepacks.default_path().read_bytes() == by_tui


# ------------------------------------------------------------ the downloads
@pytest.fixture
def choir(tmp_path, monkeypatch):
    url, sha = make_archive(tmp_path / "choir.7z")
    monkeypatch.setitem(voicesetup.CATALOG, CHOIR,
                        voicesetup.Source(**{**voicesetup.CATALOG[CHOIR].__dict__, "url": url, "sha256": sha}))


@needs_bsdtar
@pytest.mark.asyncio
async def test_installing_the_choir_leaves_what_setup_voices_leaves(choir, capsys, dirs, tmp_path):
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_voices(pilot)
        await press(pilot, "setup-voices")
        assert status(screen).startswith(f"installed {voicesetup.voices_dir() / CHOIR} (SHA-256 verified")
        on_screen = shown(screen)
        assert screen.query_one("#voices-progress", ProgressBar).percentage == 1
    assert on_screen == cli(capsys, "voices", "list")[1]
    by_tui = tree(tmp_path / "A")
    dirs("B")
    assert cli(capsys, "setup-voices", CHOIR)[0] == 0
    assert tree(tmp_path / "B") == by_tui


@needs_bsdtar
@pytest.mark.asyncio
async def test_a_failed_choir_install_says_why_and_leaves_nothing(choir, monkeypatch, tmp_path):
    entry = voicesetup.CATALOG[CHOIR]
    monkeypatch.setitem(voicesetup.CATALOG, CHOIR, voicesetup.Source(**{**entry.__dict__, "sha256": "0" * 64}))
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_voices(pilot)
        await press(pilot, "setup-voices")
        assert "checksum mismatch" in status(screen)
    assert tree(tmp_path / "A") == {}


@pytest.mark.asyncio
async def test_installing_the_soundfont_leaves_what_setup_samples_leaves(capsys, dirs, tmp_path, monkeypatch):
    url, sha = make_deb(tmp_path / "fluid.deb")
    monkeypatch.setattr(samples, "DEB_URL", url)
    monkeypatch.setattr(samples, "DEB_SHA256", sha)
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_voices(pilot)
        await press(pilot, "setup-samples")
        sf2 = samples.cache_dir() / samples.SF2_NAME
        assert status(screen) == f"installed {sf2} (SHA-256 verified; license: {sf2.parent / samples.LICENSES_NAME})"
        assert sf2.read_bytes() == SF2
        await press(pilot, "setup-samples")                                    # a second time: as the CLI says
        assert status(screen) == (f"FluidR3_GM already installed: {sf2} "
                                  f"(license: {sf2.parent / samples.LICENSES_NAME})")
    by_tui = tree(tmp_path / "A")
    dirs("B")
    assert cli(capsys, "setup-samples")[0] == 0
    assert tree(tmp_path / "B") == by_tui


@pytest.mark.asyncio
async def test_a_failed_soundfont_install_says_why_and_leaves_nothing(tmp_path, monkeypatch):
    url, _ = make_deb(tmp_path / "fluid.deb")
    monkeypatch.setattr(samples, "DEB_URL", url)
    monkeypatch.setattr(samples, "DEB_SHA256", "0" * 64)
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_voices(pilot)
        await press(pilot, "setup-samples")
        assert "checksum mismatch" in status(screen)
    assert tree(tmp_path / "A") == {}


@pytest.mark.asyncio
async def test_a_download_shows_progress_and_the_ui_stays_responsive(monkeypatch):
    release, reached = threading.Event(), threading.Event()

    def slow(key, progress=None):
        assert progress is not None
        progress(50, 200)
        reached.set()
        release.wait(10)
        progress(200, 200)
        return voicesetup.voices_dir() / key

    monkeypatch.setattr(voicesetup, "setup_voices", slow)
    app, _ = make_app(FakeShell())
    async with app.run_test() as pilot:
        screen = await open_voices(pilot)
        await pilot.click("#setup-voices")
        assert reached.wait(5)
        await pilot.pause(0.2)
        bar = screen.query_one("#voices-progress", ProgressBar)
        assert bar.progress == 50 and bar.total == 200                         # the bar moves while it downloads
        assert screen.query_one("#setup-voices", Button).disabled              # no second download meanwhile
        screen.query_one("#voices-folder", Input).value = "typed meanwhile"    # the UI still answers
        await pilot.pause(0.1)
        assert screen.query_one("#voices-folder", Input).value == "typed meanwhile"
        release.set()
        await pilot.app.workers.wait_for_complete()
        await pilot.pause(0.2)
        assert bar.percentage == 1 and not screen.query_one("#setup-voices", Button).disabled


def test_the_palette_offers_voices():
    assert "Voices and samples" in {title for title, _, _ in StreamApp.palette_actions()}


@pytest.mark.asyncio
async def test_everything_fits_in_80_by_24():
    app, _ = make_app(FakeShell())
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_voices(pilot)
        for name in ("voices-list", "voices-folder", "add", "remove", "setup-voices", "setup-samples", "cancel",
                     "voices-progress", "voices-status"):
            region = screen.query_one(f"#{name}").region
            assert region.width > 0 and region.right <= 80 and region.bottom <= 24, name
