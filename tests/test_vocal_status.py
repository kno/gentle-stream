"""PM-024: audible choir status and journey automation."""
from typing import cast

import pytest

from gentle_stream import daemon
from gentle_stream.app import StreamApp
from gentle_stream.bridge import GentleShell
from gentle_stream.client import PlayerClient
from gentle_stream.engine import Engine
from gentle_stream.journey import Journey
from gentle_stream.player import Player
from gentle_stream.presets import PresetStore
from gentle_stream.style import Style
from tests.test_app import FakeShell, text
from tests.test_player import FakeStream


def test_status_and_client_report_the_audible_vocal_level():
    engine = Engine(Style(voice=0.5), seed=3, samples=False)
    player = Player(engine, stream_factory=FakeStream)
    state = daemon.state(player)
    assert state["vocals"] == {"backend": "procedural", "level": 0.5}
    client = object.__new__(PlayerClient)
    client._update(state)
    assert client.vocals_backend == "procedural"
    assert client.now.style.voice == 0.5
    # Older daemons have no vocal status: do not claim a known backend.
    del state["vocals"]
    client._update(state)
    assert client.vocals_backend == "unknown"


@pytest.mark.asyncio
async def test_tui_shows_vocal_backend_and_level(tmp_path):
    player = Player(Engine(Style(voice=0.5), seed=3, samples=False), stream_factory=FakeStream)
    app = StreamApp(player, cast(GentleShell, FakeShell()), presets=PresetStore(tmp_path / "presets.json"))
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        assert text(app, "#vocals") == "Vocals: choir (procedural) · 50%"
        assert app.query_one("#vocals").display


def test_journey_drives_voice_and_preserves_other_fields():
    journey = Journey.from_dict({"version": 1, "name": "choir", "title": "Choir", "end": "sustain",
                                 "stages": [{"name": "Enter", "seconds": 10, "to": {"voice": 0.5}},
                                            {"name": "Leave", "seconds": 10, "to": {"voice": 0}}]})
    engine = Engine(Style(voice=0, energy=0.4), seed=3, samples=False)
    engine.queue_journey(journey)
    levels = []
    for _ in range(9):
        engine.render_bar()
        levels.append(engine.style.voice)
        assert engine.style.energy == 0.4
    assert max(levels) > 0.3
    assert levels[-1] == 0
