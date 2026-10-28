"""PM-034: edit the running journey in natural language, keeping its position (the model is always faked here)."""
import pytest

from gentle_stream import bridge, daemon, journey_command
from gentle_stream.bridge import GentleShell, InterpretError
from gentle_stream.engine import Engine, JourneyControlError
from gentle_stream.journey import Journey, map_position, stage_diff
from gentle_stream.style import Style

BPM = 120.0   # one bar is 2 s


def make(*stages, name="talk", title="Talk"):
    return Journey.from_dict({"version": 1, "name": name, "title": title, "end": "sustain",
                              "stages": [dict(s) for s in stages]})


OLD = make({"name": "Warm", "seconds": 60, "to": {"energy": 0.3}},
           {"name": "Build", "seconds": 120, "to": {"energy": 0.6}},
           {"name": "Cool", "seconds": 60, "to": {"energy": 0.2}})
LONGER = make({"name": "Warm", "seconds": 30, "to": {"energy": 0.3}},
              {"name": "Build", "seconds": 300, "to": {"energy": 0.8}},
              {"name": "Peak", "seconds": 60, "to": {"energy": 0.9}, "genre": "synthwave"})


# ------------------------------------------------------------ position
def test_a_surviving_stage_keeps_the_time_into_it():
    assert map_position(OLD, 100, LONGER) == pytest.approx(30 + 40)       # 40 s into "Build" either way


def test_stage_names_match_without_case():
    renamed = make({"name": "warm", "seconds": 10, "to": {}}, {"name": "BUILD", "seconds": 200, "to": {}})
    assert map_position(OLD, 100, renamed) == pytest.approx(10 + 40)


def test_a_shorter_surviving_stage_keeps_the_position_inside_it():
    short = make({"name": "Warm", "seconds": 60, "to": {}}, {"name": "Build", "seconds": 20, "to": {}},
                 {"name": "Cool", "seconds": 60, "to": {}})
    t = map_position(OLD, 100, short)                                      # 40 s into a stage now 20 s long
    assert short.stage_index(t) == 1 and 60 < t < 80


def test_without_the_stage_the_elapsed_time_is_kept():
    other = make({"name": "Intro", "seconds": 90, "to": {}}, {"name": "Main", "seconds": 300, "to": {}})
    assert map_position(OLD, 100, other) == pytest.approx(100)


def test_by_time_past_the_new_end_it_holds_the_end():
    tiny = make({"name": "Only", "seconds": 50, "to": {}})
    assert map_position(OLD, 100, tiny) == pytest.approx(50)


# ------------------------------------------------------------ the diff
def test_the_stage_diff_names_kept_changed_added_and_removed_stages():
    assert stage_diff(OLD, LONGER) == [
        "  ~ Warm: 60 s -> 30 s",
        "  ~ Build: 120 s -> 300 s; to.energy 0.6 -> 0.8",
        "  + Peak: 60 s, genre synthwave",
        "  - Cool: 60 s",
    ]


def test_an_unchanged_stage_is_listed_as_kept():
    assert stage_diff(OLD, OLD) == ["  = Warm: 60 s", "  = Build: 120 s", "  = Cool: 60 s"]


def test_other_stage_settings_are_named_when_they_change():
    a = make({"name": "S", "seconds": 60, "to": {"energy": 0.5, "bpm": 80}})
    b = make({"name": "S", "seconds": 60, "to": {"energy": 0.5, "voice": 0.4}, "curve": "ease-in",
              "layers": {"drums": False}, "phrases": ["Go"]})
    assert stage_diff(a, b) == ["  ~ S: to.bpm 80 -> (unset); to.voice (unset) -> 0.4; curve linear -> ease-in; "
                                "layers, phrases changed"]


# ------------------------------------------------------------ the engine
def run_to(e, seconds):
    while e.samples_out < seconds * e.sr:
        e.render_bar()


def test_the_engine_swaps_the_journey_at_the_next_bar_keeping_the_position():
    e = Engine(Style(bpm=BPM), seed=2, samples=False)
    e.queue_journey(OLD)
    run_to(e, 100)                                                        # 40 s into "Build"
    e.queue_journey_edit(LONGER)
    e.render_bar()                                                        # the bar from 100 s to 102 s
    snap = e.journey_snapshot
    assert e.journey is LONGER and snap is not None
    assert (snap.stage_name, snap.stage, snap.stages) == ("Build", 2, 3)
    assert snap.progress == pytest.approx(40 / 300)                       # 40 s into the new 300 s "Build"


def test_editing_without_a_running_journey_is_refused():
    e = Engine(Style(bpm=BPM), seed=2, samples=False)
    with pytest.raises(JourneyControlError, match="no journey is running"):
        e.queue_journey_edit(LONGER)


def test_the_edit_keeps_the_values_the_journey_started_from():
    """Only the first stage ramps from the start values: edit in the middle of it."""
    slow_warm = make({"name": "Warm", "seconds": 120, "to": {"energy": 0.3}},
                     {"name": "Build", "seconds": 120, "to": {"energy": 0.6}})
    e = Engine(Style(bpm=BPM, energy=0.1), seed=2, samples=False)
    e.queue_journey(OLD)
    run_to(e, 30)                                         # halfway through Warm: energy 0.2 by now
    e.queue_journey_edit(slow_warm)
    e.render_bar()
    # 30 s into a 120 s ramp from the journey's start (0.1) to 0.3, not from where the music is now (0.2)
    assert e.style.energy == pytest.approx(0.1 + (0.3 - 0.1) * 30 / 120, abs=0.01)


# ------------------------------------------------------------ the player
def test_the_player_reports_the_running_journey_and_applies_an_edit():
    from tests.test_daemon import fake_player

    player = fake_player()
    assert daemon.handle(player, {"cmd": "journey_current"}) == {"ok": True, "journey": None}
    assert daemon.handle(player, {"cmd": "journey_edit", "journey": LONGER.to_dict()}) == {
        "ok": False, "error": "no journey is running"}
    player.engine.queue_journey(OLD)
    player.engine.render_bar()
    assert daemon.handle(player, {"cmd": "journey_current"})["journey"] == OLD.to_dict()
    assert daemon.handle(player, {"cmd": "journey_edit", "journey": LONGER.to_dict()})["ok"]
    assert getattr(player, "last_journey", None) == LONGER.to_dict()
    player.engine.render_bar()
    assert daemon.handle(player, {"cmd": "journey_current"})["journey"] == LONGER.to_dict()


# ------------------------------------------------------------ the command
class FakeClient:
    def __init__(self, current: Journey | None = OLD, t=100.0):
        self.current, self.edits, self.detached = current, [], False
        snap = current.snapshot(t, dict.fromkeys(current.fields, 0.5), BPM) if current is not None else None

        class Now:
            journey = snap
        self.now = Now()

    def journey_current(self):
        return self.current.to_dict() if self.current is not None else None

    def journey_edit(self, data):
        self.edits.append(data)

    def detach(self):
        self.detached = True


@pytest.fixture
def cli(monkeypatch):
    """The fake player and the fake model; returns them."""
    from gentle_stream import client

    fake = FakeClient()
    asked = []
    monkeypatch.setattr(client, "connect", lambda: fake)
    monkeypatch.setattr(GentleShell, "journey_edit",
                        lambda self, current, position, prompt: asked.append((current, position, prompt)) or
                        (LONGER, None))
    return fake, asked


DIFF = ('Journey "Talk" (3 stages, 4:00) -> "Talk" (3 stages, 6:30)\n'
        "  ~ Warm: 60 s -> 30 s\n"
        "  ~ Build: 120 s -> 300 s; to.energy 0.6 -> 0.8\n"
        "  + Peak: 60 s, genre synthwave\n"
        "  - Cool: 60 s\n"
        'Position: "Build" 0:40 in (1:40) -> "Build" 0:40 in (1:10)\n')


def test_edit_with_yes_shows_the_diff_and_applies_it(cli, capsys):
    fake, asked = cli
    assert journey_command("edit", prompt="make the build-up longer", yes=True) == 0
    out, err = capsys.readouterr()
    assert out == DIFF + 'Edited journey "Talk"\n' and err == ""
    assert fake.edits == [LONGER.to_dict()] and fake.detached
    (current, position, prompt) = asked[0]
    assert current == OLD.to_dict() and prompt == "make the build-up longer"
    assert position == 'stage 2 of 3 "Build", 0:40 into its 2:00 (1:40 into the journey)'


def test_edit_asks_before_applying_on_a_terminal(cli, capsys, monkeypatch):
    fake, _ = cli
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert journey_command("edit", prompt="longer") == 0
    assert capsys.readouterr().out == DIFF + "Kept the running journey\n" and fake.edits == []
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert journey_command("edit", prompt="longer") == 0
    assert capsys.readouterr().out.endswith('Edited journey "Talk"\n') and len(fake.edits) == 1


def test_edit_without_a_terminal_needs_yes(cli, capsys, monkeypatch):
    fake, _ = cli
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert journey_command("edit", prompt="longer") == 1
    out, err = capsys.readouterr()
    assert out == DIFF and err == "gentle-stream: not applied; run it again with --yes to apply it\n"
    assert fake.edits == []


def test_edit_needs_a_running_journey(monkeypatch, capsys):
    from gentle_stream import client
    monkeypatch.setattr(client, "connect", lambda: FakeClient(current=None))
    monkeypatch.setattr(GentleShell, "journey_edit", lambda *a: pytest.fail("asked the model"))
    assert journey_command("edit", prompt="longer", yes=True) == 1
    assert capsys.readouterr() == ("", "gentle-stream: no journey is running\n")


def test_edit_without_a_player(monkeypatch, capsys):
    from gentle_stream import client

    def none():
        raise client.NoPlayer("nothing is playing")

    monkeypatch.setattr(client, "connect", none)
    assert journey_command("edit", prompt="longer", yes=True) == 1
    assert capsys.readouterr() == ("", "gentle-stream: nothing is playing\n")


def test_a_model_error_changes_nothing(cli, monkeypatch, capsys):
    fake, _ = cli

    def fail(*a):
        raise InterpretError("invalid journey: stage 1: seconds must be above 0")

    monkeypatch.setattr(GentleShell, "journey_edit", fail)
    assert journey_command("edit", prompt="longer", yes=True) == 1
    assert capsys.readouterr() == ("", "gentle-stream: invalid journey: stage 1: seconds must be above 0\n")
    assert fake.edits == []


def test_the_cli_parses_journey_edit(monkeypatch):
    from gentle_stream import main
    seen = []
    monkeypatch.setattr("gentle_stream.journey_command", lambda action, name=None, **k: seen.append((action, k)) or 0)
    assert main(["journey", "edit", "longer build-up", "--yes"]) == 0
    assert seen[0][0] == "edit" and seen[0][1]["prompt"] == "longer build-up" and seen[0][1]["yes"] is True


# ------------------------------------------------------------ the prompt
def test_the_edit_prompt_carries_the_journey_the_position_and_the_rules(monkeypatch):
    sent = []
    monkeypatch.setattr(GentleShell, "_run", lambda self, cmd: sent.append(cmd) or LONGER_JSON)
    shell = GentleShell(binary="gentle-shell")
    edited, _ = shell.journey_edit(OLD.to_dict(), 'stage 2 of 3 "Build"', "make the build-up longer")
    assert edited.to_dict() == LONGER.to_dict()
    prompt = sent[0][-1]
    assert "make the build-up longer" in prompt and '"name": "Build"' in prompt and 'stage 2 of 3 "Build"' in prompt
    assert "Keep the name of every stage that stays" in prompt
    assert "never claim health, therapeutic or medical effects" in prompt     # the same rules as journey create


def test_an_invalid_edit_answer_is_an_interpret_error(monkeypatch):
    monkeypatch.setattr(GentleShell, "_run", lambda self, cmd: '{"version": 1, "name": "x", "stages": []}')
    with pytest.raises(InterpretError, match="invalid journey"):
        GentleShell(binary="gentle-shell").journey_edit(OLD.to_dict(), "stage 1", "x")


LONGER_JSON = __import__("json").dumps(LONGER.to_dict())
assert bridge   # the module the prompt lives in
