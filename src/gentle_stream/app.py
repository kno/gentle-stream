"""Interactive TUI: what is playing, a live spectrum, play/pause/next, and a mood prompt.

The player is usually the background player (`client.PlayerClient`), so `b` leaves with the music still playing and
`q` stops it; an in-process `Player` works the same way, except that it always stops with the app.

The mood is interpreted by Gentle Shell in a thread worker while the music keeps playing; the new style starts at
the next bar. Everything shown comes from `player.now`, i.e. the bar that is audible right now. What is audible can
be saved under a name and applied later, instantly, without asking Gentle Shell again. While a journey runs, a line
shows its progress (`journey_line`), hidden otherwise. The `j` key opens a menu to restart, skip, or stop the journey; `J` picks a journey to
play (built-in or saved) or creates one from a description with Gentle Shell.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    OptionList,
    ProgressBar,
    Select,
    Static,
)
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState, get_current_worker

from .binaural import Binaural
from .bridge import GentleShell, InterpretError, Usage
from .journey import (
    BUILTIN,
    Journey,
    JourneySnapshot,
    JourneyStore,
    JourneyStoreError,
    edit_preview,
)
from .lines import binaural_line, format_time, journey_line
from .player import Player
from .presets import NAME_MAX, Preset, PresetError, PresetStore, normalize_name
from .recorder import RecordError
from .style import Style

DEFAULT_MODEL_LABEL = "Gentle Shell default"
BLOCKS = " ▁▂▃▄▅▆▇█"

# gentlemanprogramming.com palette
GENTLEMAN_THEME = Theme(
    name="gentleman",
    primary="#ff76c3",        # rose
    secondary="#f095c8",
    accent="#ffb1dd",         # pink
    foreground="#f6eff3",
    background="#140a12",
    surface="#241822",
    panel="#342230",
    success="#b4e7c7",
    warning="#f2b86d",        # peach
    error="#ff718f",
    dark=True,
    variables={
        "text-muted": "#a78e9b",
        "border": "#ff76c3",
        "border-blurred": "#342230",
        "block-cursor-foreground": "#140a12",
        "block-cursor-background": "#ff76c3",
        "block-cursor-blurred-background": "#342230",
        "block-hover-background": "#342230",
        "input-cursor-background": "#ff76c3",
        "input-cursor-foreground": "#140a12",
        "input-selection-background": "#ff76c3 30%",
        "footer-background": "#1a1218",
        "footer-key-foreground": "#ff76c3",
        "footer-description-foreground": "#a78e9b",
        "scrollbar": "#342230",
        "scrollbar-hover": "#76616b",
        "scrollbar-active": "#ff76c3",
        "scrollbar-background": "#1a1218",
    },
)
# spectrum rows, top to bottom: rose peaks over a muted base
SPECTRUM_COLORS = ("#ff76c3", "#f095c8", "#ffb1dd", "#a78e9b", "#76616b")


def model_label(model: str | None) -> str:
    return model or DEFAULT_MODEL_LABEL


class Spectrum(Static):
    """Block-character bars filling the widget, one column per log-spaced band, shaded from rose (top) to muted."""

    MIN_ROWS = 5

    def __init__(self, player: Player, **kw):
        super().__init__(**kw)
        self.player = player

    def tick(self) -> None:
        width = max(8, self.size.width or 48)
        rows_n = max(self.MIN_ROWS, self.size.height or self.MIN_ROWS)
        levels = self.player.spectrum(width) * rows_n * 8
        rows = []
        for i, r in enumerate(range(rows_n - 1, -1, -1)):    # i = 0 is the top row
            color = SPECTRUM_COLORS[min(len(SPECTRUM_COLORS) - 1, i * len(SPECTRUM_COLORS) // rows_n)]
            cell = (levels - r * 8).clip(0, 8).astype(int)
            rows.append(Text("".join(BLOCKS[c] for c in cell), style=color))
        self.update(Text("\n").join(rows))


class ModelPicker(ModalScreen[str | None]):
    """Choose the model Gentle Shell uses to interpret moods."""

    BINDINGS = [Binding("escape", "dismiss_picker", "Cancel")]
    DEFAULT_CSS = """
    ModelPicker { align: center middle; }
    ModelPicker > Vertical { width: 60; height: auto; max-height: 80%; border: round $primary; padding: 0 1;
                             background: $surface; }
    ModelPicker .heading { color: $primary; text-style: bold; }
    ModelPicker #picker-status { color: $text-muted; }
    ModelPicker OptionList, ModelPicker OptionList:focus { height: auto; max-height: 20; border: none;
                                                          background: $surface; }
    """

    def __init__(self, shell: GentleShell):
        super().__init__()
        self.shell = shell

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Model for mood interpretation", classes="heading")
            yield Static("Loading models…", id="picker-status")
            yield OptionList(Option(DEFAULT_MODEL_LABEL, id=""), id="models")

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()
        self._load()

    @work(thread=True, exclusive=True)
    def _load(self) -> None:
        try:
            models = self.shell.list_models()
        except InterpretError as e:
            self.app.call_from_thread(self.query_one("#picker-status", Static).update, f"Could not list models: {escape(str(e))}")
            return
        self.app.call_from_thread(self._show, models)

    def _show(self, models: list[str]) -> None:
        options = self.query_one(OptionList)
        options.add_options([Option(m, id=m) for m in models])
        options.highlighted = 0
        self.query_one("#picker-status", Static).update(f"{len(models)} models · current: {model_label(self.shell.model)}")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id or None)

    def action_dismiss_picker(self) -> None:
        self.dismiss(self.shell.model)


class SaveDialog(ModalScreen[str | None]):
    """Name the style that is audible now; Enter saves, Esc cancels."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    SaveDialog { align: center middle; }
    SaveDialog > Vertical { width: 60; height: auto; border: round $primary; padding: 0 1; background: $surface; }
    SaveDialog .heading { color: $primary; text-style: bold; }
    SaveDialog #save-status { color: $text-muted; }
    SaveDialog Input { border: round $panel; background: $surface; }
    SaveDialog Input:focus { border: round $primary; }
    """

    def __init__(self, name: str, heading: str = "Save what is playing"):
        super().__init__()
        self.initial, self.heading = name, heading

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.heading, classes="heading")
            yield Input(self.initial, placeholder="Name", max_length=NAME_MAX, id="save-name")
            yield Static("Enter to save · Esc to cancel", id="save-status")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()  # otherwise it bubbles to the app and is taken as a mood
        try:
            self.dismiss(normalize_name(event.value))
        except PresetError as e:
            self.query_one("#save-status", Static).update(f"[$error]{escape(str(e))}[/]")

    def action_cancel(self) -> None:
        self.dismiss(None)


class RecordDialog(ModalScreen[str | None]):
    """Record the session into a WAV file; Enter starts (the player checks the file), Esc cancels."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    RecordDialog { align: center middle; }
    RecordDialog > Vertical { width: 80; height: auto; border: round $primary; padding: 0 1; background: $surface; }
    RecordDialog .heading { color: $primary; text-style: bold; }
    RecordDialog #record-status { color: $text-muted; }
    RecordDialog Input { border: round $panel; background: $surface; }
    RecordDialog Input:focus { border: round $primary; }
    """

    def __init__(self, player):
        super().__init__()
        self.player = player

    def compose(self) -> ComposeResult:
        proposed = Path.home() / f"gentle-stream-{datetime.now():%Y%m%d-%H%M%S}.wav"
        with Vertical():
            yield Static("Record the session", classes="heading")
            yield Input(str(proposed), placeholder="FILE.wav", id="record-path")
            yield Static("Everything you hear is saved until you press r again · Enter to start · Esc to cancel",
                         id="record-status")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        from .client import PlayerError

        event.stop()  # otherwise it bubbles to the app and is taken as a mood
        path = str(Path(event.value.strip()).expanduser().resolve())
        try:
            self.player.record_start(path)
        except (RecordError, PlayerError) as e:
            self.query_one("#record-status", Static).update(f"[$error]{escape(str(e))}[/]")
            return
        self.dismiss(path)

    def action_cancel(self) -> None:
        self.dismiss(None)


class GentleCommands(Provider):
    """The command palette (ctrl+p): every action of the app, found by name."""

    async def discover(self) -> Hits:
        for title, help_text, action in StreamApp.palette_actions():
            yield DiscoveryHit(title, self._run(action), help=help_text)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for title, help_text, action in StreamApp.palette_actions():
            score = matcher.match(title)
            if score > 0:
                yield Hit(score, matcher.highlight(title), self._run(action), help=help_text)

    def _run(self, action: str):
        async def run() -> None:
            await self.app.run_action(action)
        return run


class PresetPicker(ModalScreen[Preset | None]):
    """Saved prompts: Enter applies the highlighted one, d deletes it, Esc closes."""

    BINDINGS = [
        Binding("escape", "cancel", "Close"),
        Binding("d,delete", "delete", "Delete"),
    ]
    DEFAULT_CSS = """
    PresetPicker { align: center middle; }
    PresetPicker > Vertical { width: 72; height: auto; max-height: 80%; border: round $primary; padding: 0 1;
                              background: $surface; }
    PresetPicker .heading { color: $primary; text-style: bold; }
    PresetPicker #presets-status { color: $text-muted; }
    PresetPicker OptionList, PresetPicker OptionList:focus { height: auto; max-height: 20; border: none;
                                                            background: $surface; }
    """
    EMPTY = "No saved prompts yet — press s to save what is playing"

    def __init__(self, store: PresetStore):
        super().__init__()
        self.store = store

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Saved prompts", classes="heading")
            yield Static(id="presets-status")
            yield OptionList(id="presets")

    def on_mount(self) -> None:
        options = self.query_one(OptionList)
        options.add_options([Option(Text(f"{p.name} — {p.mood or p.style.summary()}"), id=p.name)
                             for p in self.store.list()])
        if options.option_count:
            options.highlighted = 0
        self._show_status(self.store.error)
        options.focus()

    def _show_status(self, error: str | None = None) -> None:
        if error:
            text = f"[$error]{escape(error)}[/]"
        elif self.query_one(OptionList).option_count:
            text = "Enter to apply · d to delete · Esc to close"
        else:
            text = self.EMPTY
        self.query_one("#presets-status", Static).update(text)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        option_id = event.option.id
        if option_id is None:
            return
        preset = self.store.get(option_id)
        if preset is None:
            self._show_status(self.store.error or f"“{option_id}” is no longer saved.")
            return
        self.dismiss(preset)

    def action_delete(self) -> None:
        options = self.query_one(OptionList)
        if options.highlighted is None:
            return
        option = options.get_option_at_index(options.highlighted)
        option_id = option.id
        if option_id is None:
            return
        try:
            self.store.delete(option_id)
        except PresetError as e:
            self._show_status(str(e))
            return
        options.remove_option(option_id)
        self._show_status()

    def action_cancel(self) -> None:
        self.dismiss(None)


class JourneyMenu(ModalScreen[str | None]):
    """Choose a journey control: restart, skip, or stop."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    JourneyMenu { align: center middle; }
    JourneyMenu > Vertical { width: 60; height: auto; border: round $primary; padding: 0 1;
                             background: $surface; }
    JourneyMenu .heading { color: $primary; text-style: bold; }
    JourneyMenu OptionList, JourneyMenu OptionList:focus { height: auto; max-height: 20; border: none;
                                                          background: $surface; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Journey", classes="heading")
            yield Static("Restart · Skip stage · Stop · Edit with words · Save as", id="journey-status")
            yield OptionList(id="journey-options")

    def on_mount(self) -> None:
        options = self.query_one(OptionList)
        options.add_options([
            Option("Restart", id="restart"),
            Option("Skip stage", id="skip"),
            Option("Stop", id="stop"),
            Option("Edit with words…", id="edit"),
            Option("Save as…", id="save"),
        ])
        options.highlighted = 0
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id or None)

    def action_cancel(self) -> None:
        self.dismiss(None)



class JourneyPromptModal(ModalScreen[str | None]):
    """Create a journey from a natural-language description; dismisses with the saved name.

    Gentle Shell runs in a thread worker; on any error the modal stays open with the error and the input kept."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    JourneyPromptModal { align: center middle; }
    JourneyPromptModal > Vertical { width: 70; height: auto; border: round $primary; padding: 1;
                                    background: $surface; }
    JourneyPromptModal .heading { color: $primary; text-style: bold; margin-bottom: 1; }
    JourneyPromptModal Input { margin-bottom: 1; }
    JourneyPromptModal #journey-error { color: $error; }
    JourneyPromptModal #buttons { height: auto; margin-top: 1; }
    JourneyPromptModal Button { margin-right: 1; }
    """

    def __init__(self, shell: GentleShell, store: JourneyStore):
        super().__init__()
        self.shell, self.store = shell, store
        self.usage: Usage | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Create a journey", classes="heading")
            yield Static("Describe the journey you want (e.g. 'calm morning rising to energetic peak')")
            yield Input(placeholder="Journey description", id="prompt")
            yield Input(placeholder="Name (optional: the generated one otherwise)", id="name")
            yield Static("", id="journey-error", markup=False)
            with Horizontal(id="buttons"):
                yield Button("Create", id="create", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()   # never a mood request for the app below
        self._create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create":
            self._create()
        elif event.button.id == "cancel":
            self.action_cancel()

    def _create(self) -> None:
        prompt = self.query_one("#prompt", Input).value.strip()
        if not prompt:
            return
        self._show("Creating the journey with Gentle Shell…")
        self._generate(prompt, self.query_one("#name", Input).value.strip())

    def _show(self, message: str) -> None:
        self.query_one("#journey-error", Static).update(message)

    @work(thread=True, exclusive=True, group="journey-create")
    def _generate(self, prompt: str, name: str) -> None:
        worker = get_current_worker()
        try:
            journey, usage = self.shell.journey_from_prompt(prompt)
        except (InterpretError, ValueError) as e:
            if not worker.is_cancelled:
                self.app.call_from_thread(self._show, f"Could not create the journey: {e}")
            return
        if worker.is_cancelled:
            return
        chosen_name = name or journey.name or prompt
        try:
            stored_name, _ = self.store.save(chosen_name, journey)
        except JourneyStoreError as e:
            self.app.call_from_thread(self._show, f"Could not save the journey: {e}")
            return
        self.usage = usage
        self.app.call_from_thread(self.dismiss, stored_name)

    def action_cancel(self) -> None:
        self.workers.cancel_group(self, "journey-create")
        self.dismiss(None)


class JourneyEditModal(ModalScreen[Journey | None]):
    """Edit the running journey in words (PM-039): the model's answer is shown as `journey edit` shows it (stage diff,
    where the listener lands) and dismissed with the edited journey only when Apply is pressed."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    JourneyEditModal { align: center middle; }
    JourneyEditModal > Vertical { width: 90; height: auto; border: round $primary; padding: 1; background: $surface; }
    JourneyEditModal .heading { color: $primary; text-style: bold; margin-bottom: 1; }
    JourneyEditModal #edit-diff { margin: 1 0; }
    JourneyEditModal #buttons { height: auto; }
    JourneyEditModal Button { margin-right: 1; }
    """

    def __init__(self, shell: GentleShell, current: dict, snap: JourneySnapshot):
        super().__init__()
        self.shell, self.current, self.snap = shell, current, snap
        self.edited: Journey | None = None
        self.usage: Usage | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Edit the running journey", classes="heading")
            yield Input(placeholder="What to change, e.g. 'make the build-up five minutes longer'", id="edit-prompt")
            yield Static("Enter asks the model; nothing changes until you press Apply", id="edit-diff", markup=False)
            with Horizontal(id="buttons"):
                yield Button("Apply", id="apply", variant="primary", disabled=True)
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        request = event.value.strip()
        if request:
            self.edited = None
            self.query_one("#apply", Button).disabled = True
            self.query_one("#edit-diff", Static).update("Asking the model…")
            self._ask(request)

    @work(thread=True, exclusive=True, group="journey-edit")
    def _ask(self, request: str) -> None:
        current = Journey.from_dict(self.current)
        position, _ = edit_preview(current, self.snap.stage, self.snap.progress, current)
        try:
            edited, usage = self.shell.journey_edit(self.current, position, request)
        except (InterpretError, ValueError) as e:
            self.app.call_from_thread(self._show, str(e), None)
            return
        self.usage = usage
        lines = edit_preview(current, self.snap.stage, self.snap.progress, edited)[1]
        self.app.call_from_thread(self._show, "\n".join(lines), edited)

    def _show(self, message: str, edited: Journey | None) -> None:
        self.edited = edited
        self.query_one("#edit-diff", Static).update(message)
        self.query_one("#apply", Button).disabled = edited is None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply" and self.edited is not None:
            self.dismiss(self.edited)
        elif event.button.id == "cancel":
            self.action_cancel()

    def action_cancel(self) -> None:
        self.workers.cancel_group(self, "journey-edit")
        self.dismiss(None)


class JourneyFileModal(ModalScreen[tuple[Journey, list[str]] | None]):
    """Open a JSON journey file (PM-039): validated and normalized as `journey validate` does; errors stay here."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    JourneyFileModal { align: center middle; }
    JourneyFileModal > Vertical { width: 80; height: auto; border: round $primary; padding: 0 1; background: $surface; }
    JourneyFileModal .heading { color: $primary; text-style: bold; }
    JourneyFileModal #journey-file-status { color: $text-muted; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Open a journey file", classes="heading")
            yield Input(placeholder="path/to/journey.json", id="journey-file")
            yield Static("Enter opens · Esc cancels", id="journey-file-status", markup=False)

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        from . import _journey_source

        event.stop()
        path = Path(event.value.strip()).expanduser()
        status = self.query_one("#journey-file-status", Static)
        if not path.is_file():
            status.update(f"no such file: {path}")
            return
        try:
            journey, warnings = _journey_source(str(path))
        except ValueError as e:
            status.update(str(e))
            return
        self.dismiss((journey, list(warnings)))

    def action_cancel(self) -> None:
        self.dismiss(None)


class JourneyShowModal(ModalScreen[str | None]):
    """A journey as `journey show` prints it, with its warnings; for an opened file, Play and Save as too."""

    BINDINGS = [Binding("escape", "cancel", "Close")]
    DEFAULT_CSS = """
    JourneyShowModal { align: center middle; }
    JourneyShowModal > Vertical { width: 90; height: 80%; border: round $primary; padding: 0 1; background: $surface; }
    JourneyShowModal .heading { color: $primary; text-style: bold; }
    JourneyShowModal #journey-warnings { color: $warning; }
    JourneyShowModal VerticalScroll { height: 1fr; }
    JourneyShowModal #buttons { height: auto; }
    JourneyShowModal Button { margin-right: 1; }
    """

    def __init__(self, journey: Journey, warnings: list[str] | None = None, actions: bool = False):
        super().__init__()
        self.journey, self.warnings, self.actions = journey, warnings or [], actions

    def compose(self) -> ComposeResult:
        import json

        with Vertical():
            yield Static(f"Journey: {escape(self.journey.title or self.journey.name)}", classes="heading")
            yield Static("\n".join(f"warning: {w}" for w in self.warnings), id="journey-warnings", markup=False)
            with VerticalScroll():
                yield Static(json.dumps(self.journey.to_dict(), ensure_ascii=False, indent=2), id="journey-json",
                             markup=False)
            with Horizontal(id="buttons"):
                if self.actions:
                    yield Button("Play", id="play", variant="primary")
                    yield Button("Save as…", id="save")
                yield Button("Close", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id if event.button.id in ("play", "save") else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ControlsModal(ModalScreen[dict | None]):
    """Live controls (PM-040): every continuous field with its value; Apply glides the changed ones over `over`
    seconds, as `ctl glide` does. Fields the running journey drives are shown and cannot be changed."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    ControlsModal { align: center middle; }
    ControlsModal > Vertical { width: 64; height: auto; border: round $primary; padding: 0 1; background: $surface; }
    ControlsModal .heading { color: $primary; text-style: bold; }
    ControlsModal .row { height: 1; }
    ControlsModal .row Static { width: 22; }
    ControlsModal .row Input { width: 1fr; }
    ControlsModal #control-status { color: $text-muted; }
    ControlsModal #buttons { height: auto; }
    ControlsModal Button { margin-right: 1; }
    """

    def __init__(self, player, style: Style, driven: tuple[str, ...]):
        super().__init__()
        self.player, self.style, self.driven = player, style, driven

    def compose(self) -> ComposeResult:
        from .engine import GLIDE_FIELDS

        with Vertical():
            yield Static("Live controls", classes="heading")
            for name, (lo, hi) in GLIDE_FIELDS.items():
                with Horizontal(classes="row"):
                    label = f"{name}{' (journey)' if name in self.driven else ''}"
                    yield Static(label, markup=False)
                    yield Input(f"{getattr(self.style, name):g}", id=f"control-{name}", placeholder=f"{lo:g}-{hi:g}",
                                disabled=name in self.driven, compact=True)
            with Horizontal(classes="row"):
                yield Static("over (s)")
                yield Input("60", id="control-over", placeholder="0-3600", compact=True)
            note = "Fields marked (journey) are driven by the journey. " if self.driven else ""
            yield Static(f"{note}Changed fields glide to their new values over the given seconds.",
                         id="control-status", markup=False)
            with Horizontal(id="buttons"):
                yield Button("Apply", id="apply", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()   # never a mood request for the app below
        self._apply()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply":
            self._apply()
        else:
            self.action_cancel()

    def _apply(self) -> None:
        import math

        from .client import PlayerError
        from .engine import GLIDE_FIELDS

        status = self.query_one("#control-status", Static)
        fields: dict[str, float] = {}
        for name in GLIDE_FIELDS:
            box = self.query_one(f"#control-{name}", Input)
            if box.disabled:
                continue
            try:
                value = float(box.value)
            except ValueError:
                status.update(f"{name} must be a number")
                return
            if not math.isfinite(value):
                status.update(f"{name} must be a number")
                return
            if abs(value - getattr(self.style, name)) > 1e-9:
                fields[name] = value
        try:
            over = float(self.query_one("#control-over", Input).value)
        except ValueError:
            over = -1.0
        if not (math.isfinite(over) and 0 <= over <= 3600):
            status.update("over must be between 0 and 3600 seconds")
            return
        if not fields:
            self.dismiss({})
            return
        try:
            self.player.glide(fields, over)
        except (ValueError, PlayerError) as e:   # a journey drives a field: the CLI's message
            status.update(str(e))
            return
        self.dismiss({"fields": fields, "over": over})

    def action_cancel(self) -> None:
        self.dismiss(None)


class BinauralModal(ModalScreen[str | None]):
    """The binaural layer (PM-041): Apply turns it on with these values when it is off (`ctl binaural on`), or
    glides the changed ones when it plays (`ctl binaural set`); Off fades it out (`ctl binaural off`). Ranges are
    checked here, before anything is sent. A listening texture only: no claim about any effect."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    BinauralModal { align: center middle; }
    BinauralModal > Vertical { width: 64; height: auto; border: round $primary; padding: 0 1; background: $surface; }
    BinauralModal .heading { color: $primary; text-style: bold; }
    BinauralModal .row { height: 1; }
    BinauralModal .row Static { width: 22; }
    BinauralModal .row Input { width: 1fr; }
    BinauralModal #binaural-status { color: $text-muted; }
    BinauralModal #buttons { height: auto; }
    BinauralModal Button { margin-right: 1; }
    """

    def __init__(self, player, setting: Binaural | None):
        super().__init__()
        self.player, self.setting = player, setting

    def compose(self) -> ComposeResult:
        shown = self.setting or Binaural()
        with Vertical():
            yield Static(f"Binaural layer · {'on' if self.setting else 'off'}", classes="heading")
            for name, label, value in (("carrier", "carrier (40-1000 Hz)", shown.carrier),
                                       ("beat", "beat (0.5-40 Hz)", shown.beat),
                                       ("level", "level (0-0.08)", shown.level),
                                       ("over", "over (0-3600 s)", 60)):
                with Horizontal(classes="row"):
                    yield Static(label)
                    yield Input(f"{value:g}", id=f"binaural-{name}", compact=True)
            yield Static("A quiet tone on each ear, the beat apart; headphones recommended. It is only a listening "
                         "texture.", id="binaural-status", markup=False)
            with Horizontal(id="buttons"):
                yield Button("Turn on" if self.setting is None else "Apply", id="apply", variant="primary")
                yield Button("Off", id="off", disabled=self.setting is None)
                yield Button("Cancel", id="cancel")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()   # never a mood request for the app below
        self._apply()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply":
            self._apply()
        elif event.button.id == "off":
            self._send(lambda: self.player.set_binaural(None, self._over() or 0.0), "off")
        else:
            self.action_cancel()

    def _over(self) -> float | None:
        import math
        try:
            over = float(self.query_one("#binaural-over", Input).value)
        except ValueError:
            return None
        return over if math.isfinite(over) and 0 <= over <= 3600 else None

    def _send(self, request, outcome: str) -> None:
        from .client import PlayerError

        try:
            request()
        except (ValueError, PlayerError) as e:   # a journey owns the layer, or it went off: the CLI's message
            self.query_one("#binaural-status", Static).update(str(e))
            return
        self.dismiss(outcome)

    def _apply(self) -> None:
        status = self.query_one("#binaural-status", Static)
        values: dict[str, float] = {}
        for name in ("carrier", "beat", "level"):
            try:
                values[name] = float(self.query_one(f"#binaural-{name}", Input).value)
            except ValueError:
                status.update(f"{name} must be a number")
                return
        try:
            setting = Binaural.from_dict(values)
        except ValueError as e:
            status.update(str(e))
            return
        over = self._over()
        if over is None:
            status.update("over must be between 0 and 3600 seconds")
            return
        if self.setting is None:
            self._send(lambda: self.player.set_binaural(setting, over), "on")
            return
        changed = {name: value for name, value in setting.to_dict().items()
                   if abs(value - getattr(self.setting, name)) > 1e-9}
        if not changed:
            self.dismiss(None)
            return
        self._send(lambda: self.player.glide_binaural(changed, over), "set")

    def action_cancel(self) -> None:
        self.dismiss(None)


class SayModal(ModalScreen[tuple[str, list[str]] | None]):
    """Say a phrase over the music (PM-042), as `ctl say` does: text, a system voice (the list comes from the
    text-to-speech program), rate and effect. The phrase is rendered in a worker; errors stay in the dialog."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    SayModal { align: center middle; }
    SayModal > Vertical { width: 72; height: auto; border: round $primary; padding: 0 1; background: $surface; }
    SayModal .heading { color: $primary; text-style: bold; }
    SayModal .row { height: auto; }
    SayModal .row Static { width: 12; padding: 1 0; }
    SayModal .row > Input, SayModal .row > Select { width: 1fr; }
    SayModal #say-status { color: $text-muted; }
    SayModal #buttons { height: auto; }
    SayModal Button { margin-right: 1; }
    """

    def __init__(self, player):
        super().__init__()
        self.player = player

    def compose(self) -> ComposeResult:
        from .speech import EFFECTS, RATES

        with Vertical():
            yield Static("Say a phrase", classes="heading")
            yield Input(placeholder="What to say (at most 200 characters)", id="say-text")
            with Horizontal(classes="row"):
                yield Static("voice")
                yield Select([("Default voice", "")], value="", allow_blank=False, id="say-voice")
            with Horizontal(classes="row"):
                yield Static("rate")
                yield Input(placeholder=f"words per minute, {RATES[0]}-{RATES[1]} (blank: the voice's own)",
                            id="say-rate")
            with Horizontal(classes="row"):
                yield Static("effect")
                yield Select([(name, name) for name in EFFECTS], value="dry", allow_blank=False, id="say-effect")
            yield Static("It starts on the next phrase boundary, the music dipping under it.", id="say-status",
                         markup=False)
            with Horizontal(id="buttons"):
                yield Button("Say", id="say", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#say-text", Input).focus()
        self._list_voices()

    @work(thread=True, group="say-voices")
    def _list_voices(self) -> None:
        from .speech import SpeechError, voices

        try:
            found = voices()
        except SpeechError as e:
            self.app.call_from_thread(self.query_one("#say-status", Static).update, str(e))
            return
        options = [("Default voice", ""), *((f"{name} ({language})", name) for name, language in found)]
        self.app.call_from_thread(self.query_one("#say-voice", Select).set_options, options)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()   # never a mood request for the app below
        self._say()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "say":
            self._say()
        else:
            self.action_cancel()

    def _say(self) -> None:
        from .speech import MAX_TEXT, RATES

        status = self.query_one("#say-status", Static)
        phrase = " ".join(self.query_one("#say-text", Input).value.split())
        if not 1 <= len(phrase) <= MAX_TEXT:
            status.update(f"a phrase must have between 1 and {MAX_TEXT} characters")
            return
        raw_rate = self.query_one("#say-rate", Input).value.strip()
        rate = None
        if raw_rate:
            try:
                rate = int(raw_rate)
            except ValueError:
                rate = -1
            if not RATES[0] <= rate <= RATES[1]:
                status.update(f"rate must be a whole number from {RATES[0]} to {RATES[1]}")
                return
        voice = self.query_one("#say-voice", Select).value
        effect = self.query_one("#say-effect", Select).value
        status.update("Rendering the phrase…")
        self._speak(phrase, str(voice) if voice else None, rate, str(effect))

    @work(thread=True, exclusive=True, group="say")
    def _speak(self, phrase: str, voice: str | None, rate: int | None, effect: str) -> tuple[str, list[str]] | str:
        """The phrase and its warnings, or the error to show; the dialog closes when this worker has finished."""
        from .client import PlayerError
        from .speech import SpeechError

        try:
            return phrase, list(self.player.say(phrase, voice=voice, rate=rate, effect=effect))
        except (SpeechError, PlayerError) as e:
            return str(e)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != "say" or event.state != WorkerState.SUCCESS:
            return
        result = event.worker.result
        if isinstance(result, str):
            self.query_one("#say-status", Static).update(result)
        elif result is not None:
            self.dismiss(result)

    def action_cancel(self) -> None:
        self.dismiss(None)


class VoicesModal(ModalScreen[None]):
    """Voice packs and the optional downloads (PM-043), with the functions of `voices add|list|remove`,
    `setup-voices` and `setup-samples`, so the store and caches end up as the CLI leaves them. A download runs in
    a worker with a progress bar; the dialog stays open until it ends."""

    BINDINGS = [Binding("escape", "cancel", "Close")]
    DEFAULT_CSS = """
    VoicesModal { align: center middle; }
    VoicesModal > Vertical { width: 96; max-width: 100%; height: auto; border: round $primary; padding: 0 1;
                             background: $surface; }
    VoicesModal .heading { color: $primary; text-style: bold; }
    VoicesModal #voices-list { height: auto; max-height: 7; }
    VoicesModal #voices-status { color: $text-muted; }
    VoicesModal .buttons { height: auto; }
    VoicesModal Button { margin-right: 1; }
    """

    CHOIR = "freepats-synth-choir"

    def __init__(self):
        super().__init__()
        self.busy = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Voice packs (* sings now) · the choir and sampled instruments", classes="heading")
            yield OptionList(id="voices-list")
            yield Input(placeholder="A pack folder to add (pack.json with its license, and the recordings)",
                        id="voices-folder")
            with Horizontal(classes="buttons"):
                yield Button("Add", id="add", variant="primary")
                yield Button("Remove", id="remove")
            with Horizontal(classes="buttons"):
                yield Button("Install FreePats choir", id="setup-voices")
                yield Button("Install FluidR3_GM", id="setup-samples")
                yield Button("Close", id="cancel")
            yield ProgressBar(id="voices-progress", show_eta=False)
            yield Static("Downloads are optional, verified by SHA-256 and kept with their licenses.",
                         id="voices-status", markup=False)

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        from .voicepacks import PackError, VoiceStore, list_lines

        options = self.query_one("#voices-list", OptionList)
        options.clear_options()
        try:
            self.entries = VoiceStore().entries()
        except PackError as e:
            self.entries = []
            self.query_one("#voices-status", Static).update(str(e))
            return
        options.add_options(list_lines(self.entries))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()   # never a mood request for the app below
        self._add()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add":
            self._add()
        elif event.button.id == "remove":
            self._remove()
        elif event.button.id in ("setup-voices", "setup-samples"):
            self._busy(True)
            self._install(event.button.id)
        else:
            self.action_cancel()

    def _add(self) -> None:
        from .voicepacks import PackError, VoiceStore, added_message

        folder = self.query_one("#voices-folder", Input).value.strip()
        status = self.query_one("#voices-status", Static)
        if not folder:
            status.update("type the folder of a voice pack")
            return
        try:
            status.update(added_message(*VoiceStore().add(str(Path(folder).expanduser()))))
        except PackError as e:
            status.update(str(e))
            return
        self._refresh()

    def _remove(self) -> None:
        from .voicepacks import PackError, VoiceStore

        index = self.query_one("#voices-list", OptionList).highlighted
        if index is None or not self.entries:
            return
        try:
            removed = VoiceStore().remove(self.entries[index][0])
        except PackError as e:
            self.query_one("#voices-status", Static).update(str(e))
            return
        if removed is not None:
            self.query_one("#voices-status", Static).update(f'Removed voice pack "{removed}"')
        self._refresh()

    def _busy(self, busy: bool) -> None:
        self.busy = busy
        for name in ("add", "remove", "setup-voices", "setup-samples"):
            self.query_one(f"#{name}", Button).disabled = busy

    @work(thread=True, exclusive=True, group="voices-setup")
    def _install(self, which: str) -> None:
        from . import samples, voicesetup
        from .voicepacks import PackError

        bar = self.query_one("#voices-progress", ProgressBar)
        status = self.query_one("#voices-status", Static)

        def progress(done: int, total: int | None) -> None:
            self.app.call_from_thread(bar.update, total=total, progress=done)

        self.app.call_from_thread(bar.update, total=None, progress=0)
        self.app.call_from_thread(status.update, "Downloading…")
        try:
            if which == "setup-voices":
                already = voicesetup.installed(self.CHOIR)
                folder = voicesetup.setup_voices(self.CHOIR, progress=progress)
                message = voicesetup.installed_message(self.CHOIR, already or folder, already is not None)
            else:
                already = samples.soundfont_path()
                sf2 = already or samples.setup_samples(progress=progress)
                message = samples.installed_message(sf2, already is not None)
        except (samples.SetupError, PackError) as e:
            message = f"{which} failed: {e}"
            self.app.call_from_thread(bar.update, total=None, progress=0)
        else:
            self.app.call_from_thread(bar.update, total=100, progress=100)
        self.app.call_from_thread(self._done, message)

    def _done(self, message: str) -> None:
        self._busy(False)
        self.query_one("#voices-status", Static).update(message)
        self._refresh()

    def action_cancel(self) -> None:
        if self.busy:   # the download thread cannot be stopped; leave once it has cleaned up after itself
            self.query_one("#voices-status", Static).update("Downloading… the dialog closes when it ends")
            return
        self.dismiss(None)


class RenderModal(ModalScreen[str | None]):
    """Render to a WAV (PM-044) with the function `gentle-stream render` uses: the style playing now (the CLI's
    `--mood-file` with it) or a built-in journey, a length, a seed (blank: random, reported) and the procedural
    instruments if asked. It runs in a worker; errors stay in the dialog. Dismisses with the line render prints."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    RenderModal { align: center middle; }
    RenderModal > Vertical { width: 72; max-width: 100%; height: auto; border: round $primary; padding: 0 1;
                             background: $surface; }
    RenderModal .heading { color: $primary; text-style: bold; }
    RenderModal .row { height: 1; }
    RenderModal .row Static { width: 22; }
    RenderModal .row Input { width: 1fr; }
    RenderModal #render-journey { margin-top: 1; }
    RenderModal #render-status { color: $text-muted; }
    RenderModal #buttons { height: auto; }
    RenderModal Button { margin-right: 1; }
    """

    def __init__(self, style: Style):
        super().__init__()
        self.style = style

    def compose(self) -> ComposeResult:
        from . import MAX_RENDER_SECONDS, RENDER_SECONDS
        from .journey import BUILTIN

        proposed = Path.home() / f"gentle-stream-render-{datetime.now():%Y%m%d-%H%M%S}.wav"
        with Vertical():
            yield Static(f"Render to a WAV file · {self.style.name}", classes="heading", markup=False)
            yield Input(str(proposed), placeholder="FILE.wav", id="render-path")
            for name, label, value in (("seconds", f"seconds (max {MAX_RENDER_SECONDS:g})", f"{RENDER_SECONDS:g}"),
                                       ("seed", "seed (blank: random)", "")):
                with Horizontal(classes="row"):
                    yield Static(label)
                    yield Input(value, id=f"render-{name}", compact=True)
            yield Select([("The style playing now", ""), *((f"Journey: {name}", name) for name in BUILTIN)],
                         value="", allow_blank=False, id="render-journey")
            yield Checkbox("Procedural instruments, even with the soundfont installed", id="render-procedural",
                           compact=True)
            yield Static("Rendered offline: what plays is not interrupted.", id="render-status", markup=False)
            with Horizontal(id="buttons"):
                yield Button("Render", id="render", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()   # never a mood request for the app below
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "render":
            self._submit()
        else:
            self.action_cancel()

    def _submit(self) -> None:
        import math

        from . import MAX_RENDER_SECONDS

        status = self.query_one("#render-status", Static)
        out = self.query_one("#render-path", Input).value.strip()
        if not out:
            status.update("type the WAV file to write")
            return
        try:
            seconds = float(self.query_one("#render-seconds", Input).value)
        except ValueError:
            seconds = math.nan
        if not 0 < seconds <= MAX_RENDER_SECONDS:   # also NaN
            status.update(f"seconds must be a number above 0 and at most {MAX_RENDER_SECONDS:g}")
            return
        raw_seed = self.query_one("#render-seed", Input).value.strip()
        seed = None
        if raw_seed:
            try:
                seed = int(raw_seed)
            except ValueError:
                seed = -1
            if seed < 0:
                status.update("seed must be a non-negative integer")
                return
        journey = self.query_one("#render-journey", Select).value
        procedural = self.query_one("#render-procedural", Checkbox).value
        for name in ("render", "cancel"):
            self.query_one(f"#{name}", Button).disabled = True
        status.update("Rendering…")
        self._render_wav(str(Path(out).expanduser()), seconds, seed, str(journey) if journey else None, procedural)

    @work(thread=True, exclusive=True, group="render")
    def _render_wav(self, out: str, seconds: float, seed: int | None, journey: str | None, procedural: bool) -> tuple[bool, str]:
        """(True, the line render prints) or (False, why it failed); the dialog reacts when the worker ends."""
        from . import RenderError, render_style

        try:
            return True, render_style(out, seconds, seed, self.style, procedural, journey)
        except RenderError as e:
            return False, str(e)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != "render" or event.state != WorkerState.SUCCESS:
            return
        ok, message = event.worker.result or (False, "")
        if ok:
            self.dismiss(message)
            return
        for name in ("render", "cancel"):
            self.query_one(f"#{name}", Button).disabled = False
        self.query_one("#render-status", Static).update(message)

    def action_cancel(self) -> None:
        if not self.query_one("#cancel", Button).disabled:   # a render in progress finishes first
            self.dismiss(None)


class BroadcastModal(ModalScreen[str | None]):
    """The live broadcast (PM-045), as `gentle-stream stream url|key` and `ctl stream start|stop`: the ingest URL, the
    stream key (typed masked, saved 0600, cleared from the field, never shown), and start or stop. Starting and
    stopping run in a worker (connecting or letting ffmpeg finish takes a moment); errors stay in the dialog."""

    BINDINGS = [Binding("escape", "cancel", "Close")]
    DEFAULT_CSS = """
    BroadcastModal { align: center middle; }
    BroadcastModal > Vertical { width: 78; max-width: 100%; height: auto; border: round $primary; padding: 0 1;
                                background: $surface; }
    BroadcastModal .heading { color: $primary; text-style: bold; }
    BroadcastModal .row { height: auto; }
    BroadcastModal .row Input { width: 1fr; }
    BroadcastModal #live-key-state, BroadcastModal #live-status { color: $text-muted; }
    BroadcastModal Button { margin-left: 1; }
    BroadcastModal #buttons Button { margin-left: 0; margin-right: 1; }
    BroadcastModal #buttons { height: auto; }
    """

    def __init__(self, player):
        super().__init__()
        self.player = player

    def compose(self) -> ComposeResult:
        from .streamconf import EXAMPLE_URL, load_url

        live = (self.player.streaming or {}).get("running")
        with Vertical():
            yield Static("Live broadcast · YouTube Live or any RTMP(S) ingest", classes="heading")
            with Horizontal(classes="row"):
                yield Input(load_url() or "", placeholder=EXAMPLE_URL, id="live-url")
                yield Button("Save URL", id="save-url")
            yield Static("", id="live-key-state", markup=False)
            with Horizontal(classes="row"):
                yield Input(placeholder="paste the stream key", password=True, id="live-key")
                yield Button("Save key", id="save-key")
                yield Button("Clear key", id="clear-key")
            yield Static(self._describe(), id="live-status", markup=False)
            with Horizontal(id="buttons"):
                if live:
                    yield Button("Stop broadcast", id="stop", variant="error")
                else:
                    yield Button("Start broadcast", id="start", variant="primary")
                yield Button("Close", id="cancel")

    def on_mount(self) -> None:
        self._show_key_state()

    def _show_key_state(self) -> None:
        from .streamconf import show_lines

        self.query_one("#live-key-state", Static).update(show_lines()[1])

    def _describe(self) -> str:
        streaming = self.player.streaming
        if not streaming:
            return "Not broadcasting. The music keeps playing here whatever happens to the broadcast."
        if streaming.get("running"):
            return (f"Broadcasting to {streaming['target']} · {format_time(streaming['seconds'])} · "
                    f"{streaming['dropped_frames']} frames dropped")
        return f"The broadcast failed: {streaming.get('error')}"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()   # never a mood request for the app below
        if event.input.id == "live-url":
            self._save_url()
        else:
            self._save_key()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {"save-url": self._save_url, "save-key": self._save_key, "clear-key": self._clear_key,
                    "start": lambda: self._run("start"), "stop": lambda: self._run("stop")}
        handlers.get(event.button.id or "", self.action_cancel)()

    def _say(self, message: str) -> None:
        self.query_one("#live-status", Static).update(message)

    def _save_url(self) -> None:
        from .streamconf import StreamConfigError, save_url

        try:
            self._say(f"Ingest URL saved: {save_url(self.query_one('#live-url', Input).value)}")
        except StreamConfigError as e:
            self._say(str(e))

    def _save_key(self) -> None:
        from .streamconf import StreamConfigError, save_key

        field = self.query_one("#live-key", Input)
        try:
            path = save_key(field.value)
        except StreamConfigError as e:
            self._say(str(e))
            return
        finally:
            field.value = ""            # never kept in the widget
        self._say(f"Stream key saved in {path} (readable only by you)")
        self._show_key_state()

    def _clear_key(self) -> None:
        from .streamconf import clear_key

        removed = clear_key()
        self._say(f"Stream key removed from {removed}" if removed else "No stream key saved")
        self._show_key_state()

    def _run(self, action: str) -> None:
        for button in self.query("#buttons Button").results(Button):
            button.disabled = True
        self._say("Connecting…" if action == "start" else "Ending the broadcast…")
        self._broadcast(action)

    @work(thread=True, exclusive=True, group="live")
    def _broadcast(self, action: str) -> tuple[bool, str]:
        """(True, what the app's status line says) or (False, why it failed); the dialog reacts when it ends."""
        from .broadcast import BroadcastError
        from .client import PlayerError

        try:
            if action == "start":
                return True, f"Broadcasting to {self.player.stream_start()['target']}"
            ended = self.player.stream_stop()
        except (BroadcastError, PlayerError) as e:
            return False, str(e)
        if ended is None:
            return False, "not broadcasting"
        seconds = round(float(ended["seconds"]))
        return True, (f"Broadcast to {ended['target']} ended after {seconds // 60}:{seconds % 60:02d} "
                      f"({ended['dropped_frames']} frames dropped)")

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != "live" or event.state != WorkerState.SUCCESS:
            return
        ok, message = event.worker.result or (False, "")
        if ok:
            self.dismiss(message)
            return
        for button in self.query("#buttons Button").results(Button):
            button.disabled = False
        self._say(message)

    def action_cancel(self) -> None:
        self.dismiss(None)


class JourneyPickerModal(ModalScreen[str | None]):
    """Pick a journey: "create" first, then the built-ins, then the saved ones alphabetically, then "open" (a file);
    `v` shows the highlighted one, `d` deletes a saved one.

    Dismisses with "create", "open", "builtin:<name>" or "saved:<name>"."""

    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("d,delete", "delete", "Delete"),
                Binding("v", "show", "Show")]
    DEFAULT_CSS = """
    JourneyPickerModal { align: center middle; }
    JourneyPickerModal > Vertical { width: 70; height: auto; border: round $primary; padding: 1;
                                    background: $surface; }
    JourneyPickerModal .heading { color: $primary; text-style: bold; margin-bottom: 1; }
    JourneyPickerModal OptionList, JourneyPickerModal OptionList:focus { height: auto; max-height: 20;
                                                                        border: none; background: $surface; }
    """

    def __init__(self, store: JourneyStore, highlight: str | None = None):
        super().__init__()
        self.store, self.highlight = store, highlight

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Pick a journey", classes="heading")
            yield OptionList(id="journey-list")
            yield Static("Enter plays · v shows · d deletes a saved journey · Esc closes", id="journey-picker-status",
                         markup=False)

    def on_mount(self) -> None:
        options = self.query_one(OptionList)
        options.add_option(Option("＋ Create from a description…", id="create"))
        for name, journey in BUILTIN.items():
            options.add_option(Option(f"[built-in] {escape(name)}: {escape(journey.description)}",
                                      id=f"builtin:{name}"))
        for saved_name, _ in self.store.list():
            options.add_option(Option(f"[saved] {escape(saved_name)}", id=f"saved:{saved_name}"))
        options.add_option(Option("📂 Open a journey file…", id="open"))   # last: the PM-012 order stays as it was
        ids = [options.get_option_at_index(i).id for i in range(options.option_count)]
        options.highlighted = ids.index(self.highlight) if self.highlight in ids else 0
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option.id or None)

    def _highlighted(self) -> str | None:
        options = self.query_one(OptionList)
        return None if options.highlighted is None else options.get_option_at_index(options.highlighted).id

    def action_delete(self) -> None:
        option_id = self._highlighted() or ""
        status = self.query_one("#journey-picker-status", Static)
        if option_id.startswith("builtin:"):
            status.update("built-in journeys cannot be deleted")
            return
        if not option_id.startswith("saved:"):
            return
        name = option_id.partition(":")[2]
        try:
            self.store.delete(name)
        except JourneyStoreError as e:
            status.update(str(e))
            return
        self.query_one(OptionList).remove_option(option_id)
        status.update(f'Deleted journey "{name}"')

    def action_show(self) -> None:
        option_id = self._highlighted() or ""
        kind, _, name = option_id.partition(":")
        journey = BUILTIN.get(name) if kind == "builtin" else self.store.get(name) if kind == "saved" else None
        if journey is not None:
            self.app.push_screen(JourneyShowModal(journey))

    def action_cancel(self) -> None:
        self.dismiss(None)


# Every CLI command and `ctl` action, with the TUI action that does the same (a key, and always the palette).
# tests/test_parity.py walks the real parser: a new command fails it until it is mapped here, or in NOT_IN_TUI with
# the reason it has no action.
PARITY: dict[str, str] = {
    "ctl play": "toggle", "ctl pause": "toggle", "ctl toggle": "toggle", "ctl next": "next", "ctl stop": "quit",
    "ctl tempo": "controls", "ctl glide": "controls", "ctl binaural": "binaural", "ctl say": "say",
    "ctl record": "record", "ctl stream": "broadcast", "ctl mute": "mute", "ctl unmute": "mute",
    "stream key": "broadcast", "stream url": "broadcast", "stream show": "broadcast",
    "journey play": "journey_picker", "journey list": "journey_picker", "journey show": "journey_picker",
    "journey delete": "journey_picker", "journey create": "journey_picker", "journey validate": "journey_open",
    "journey save": "journey_save_as", "journey stop": "journey_menu", "journey restart": "journey_menu",
    "journey skip": "journey_menu", "journey edit": "journey_edit",
    "voices add": "voices", "voices list": "voices", "voices remove": "voices",
    "setup-voices": "voices", "setup-samples": "voices",
    "render": "render",
}
NOT_IN_TUI: dict[str, str] = {
    "ctl status": "the TUI shows the state all the time (title, mood, tempo, journey, binaural, recording)",
}


class StreamApp(App):
    TITLE = "gentle-stream"
    SUB_TITLE = "real-time generative music"
    AUTO_FOCUS = None
    CSS = """
    Screen { background: $background; }
    Header { background: #1a1218; color: $primary; }
    #panel { padding: 1 2; margin: 1 1 0 1; height: 1fr; border: round $panel; background: $surface; }
    #title { text-style: bold; color: $primary; }
    #details, #model { color: $text-muted; }
    #mood-line { color: $accent; text-style: italic; }
    #journey, #binaural { color: $secondary; }
    #spectrum { height: 1fr; min-height: 5; margin: 1 0; }
    #state { color: $text-muted; }
    #status { margin-top: 1; }
    #mood { dock: bottom; margin: 0 1 1 1; border: round $panel; background: $surface; }
    #mood:focus { border: round $primary; }
    """
    COMMANDS = App.COMMANDS | {GentleCommands}
    BINDINGS = [
        Binding("space", "toggle", "Play/Pause"),
        Binding("n", "next", "Next"),
        Binding("slash", "focus_mood", "Mood"),
        Binding("m", "pick_model", "Model"),
        Binding("s", "save_preset", "Save"),
        Binding("p", "pick_preset", "Saved"),
        Binding("j", "journey_menu", "Journey"),
        Binding("J", "journey_picker", "Journeys"),
        Binding("r", "record", "Record"),
        Binding("c", "controls", "Controls"),
        Binding("B", "binaural", "Binaural"),
        Binding("t", "say", "Say"),
        Binding("v", "voices", "Voices"),
        Binding("w", "render", "Render"),
        Binding("L", "broadcast", "Live"),
        Binding("M", "mute", "Mute here"),
        Binding("plus,equals_sign", "volume(5)", "Vol +5"),
        Binding("minus", "volume(-5)", "Vol -5"),
        Binding("up", "volume(1)", "Vol +1"),
        Binding("down", "volume(-1)", "Vol -1"),
        Binding("escape", "leave_mood", show=False),
        Binding("b", "back", "Back (keeps playing)"),
        Binding("q", "quit", "Quit (stops music)"),
    ]

    def __init__(self, player: Player, shell: GentleShell, initial_mood: str | None = None,
                 presets: PresetStore | None = None):
        super().__init__()
        self.player, self.shell, self.initial_mood = player, shell, initial_mood
        self.presets = presets if presets is not None else PresetStore()
        self.session_usage: Usage | None = None  # tokens and cost of every successful interpretation so far
        self._keep_playing = False                # `b` leaves the music playing, `q` stops it
        self.register_theme(GENTLEMAN_THEME)
        self.theme = GENTLEMAN_THEME.name

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="panel"):
            yield Static(id="title")
            yield Static(id="details")
            yield Static(id="mood-line")
            yield Static(id="journey", markup=False)
            yield Static(id="binaural", markup=False)
            yield Static(id="vocals", markup=False)
            yield Spectrum(self.player, id="spectrum")
            yield Static(id="state")
            yield Static(id="model")
            yield Static("Press / to describe a mood.", id="status")
        yield Input(placeholder="Describe a feeling, a concept, a place… then Enter (Esc to leave)", id="mood")
        yield Footer()

    def on_mount(self) -> None:
        # keep references: the timer also fires while a modal is on top or the app is shutting down,
        # when queries would search another screen
        self._spectrum = self.query_one("#spectrum", Spectrum)
        self._w: dict[str, Static] = {
            "title": self.query_one("#title", Static),
            "details": self.query_one("#details", Static),
            "mood-line": self.query_one("#mood-line", Static),
            "journey": self.query_one("#journey", Static),
            "binaural": self.query_one("#binaural", Static),
            "vocals": self.query_one("#vocals", Static),
            "state": self.query_one("#state", Static),
            "model": self.query_one("#model", Static),
            "status": self.query_one("#status", Static),
        }
        self.player.start()
        self._show_model()
        self._tick()
        self.set_interval(1 / 15, self._tick)
        if self.initial_mood:
            self._request(self.initial_mood)

    def on_unmount(self) -> None:
        self.shell.cancel()  # a running gentle-shell would otherwise keep the process alive after quit
        if self._keep_playing:
            self.player.detach()
        else:
            self.player.close()

    # ------------------------------------------------------------ display
    def _tick(self) -> None:
        w = self._w
        try:
            self._spectrum.tick()   # first: polling a background player also refreshes what is shown below
        except ConnectionError:    # the background player was stopped elsewhere (`gentle-stream ctl stop`)
            self.exit(message="gentle-stream: the music was stopped")
            return
        now, p = self.player.now, self.player
        w["title"].update(f"♪ {now.style.name}")
        w["details"].update(now.style.summary())
        w["mood-line"].update(f"“{now.style.mood}”" if now.style.mood else "")
        journey = journey_line(now.journey, max(0.0, p.elapsed_seconds - now.start_seconds))
        w["journey"].update(journey)
        w["journey"].display = bool(journey)
        binaural = binaural_line(p.binaural)
        w["binaural"].update(binaural)
        w["binaural"].display = bool(binaural)
        w["vocals"].update(f"Vocals: choir ({p.vocals_backend}) · {round(now.style.voice * 100)}%")
        w["vocals"].display = now.style.voice > 0
        state = "[b $success]▶ Playing[/]" if p.playing else "[b $warning]⏸ Paused[/]"
        elapsed, remaining = format_time(p.elapsed_seconds), format_time(p.cycle_remaining_seconds)
        recording = p.recording
        rec = f" · [b $error]● REC[/] {format_time(recording[1])}" if recording is not None else ""
        if p.muted:
            rec += " · [b $warning]MUTED here[/]"
        streaming = p.streaming
        if streaming and streaming.get("running"):
            rec += f" · [b $error]● LIVE[/] {format_time(streaming['seconds'])}"
        elif streaming and streaming.get("error"):
            rec += " · [b $warning]LIVE failed[/] (L)"
        w["state"].update(f"{state} · piece {now.piece} · bar {now.bar + 1} · "
                          f"{elapsed} · -{remaining} · vol {round(p.volume * 100)}%{rec}")

    def _show_model(self) -> None:
        session = f" · session: {self.session_usage.format()}" if self.session_usage else ""
        self._w["model"].update(f"model: {escape(model_label(self.shell.model))}{session}")

    def _status(self, text: str) -> None:
        self._w["status"].update(text)

    # ------------------------------------------------------------ actions
    async def action_back(self) -> None:
        self._keep_playing = True
        self.exit()

    async def action_toggle(self, attribute_name: str = "", *, animate: bool = True) -> None:
        self.player.toggle()
        self._tick()

    def action_next(self) -> None:
        self.player.next()
        self._status("Next piece, same mood.")

    def action_volume(self, percent: int) -> None:
        """Change the volume by whole percentage points, so repeated steps never drift."""
        self.player.set_volume((round(self.player.volume * 100) + percent) / 100)
        self._tick()

    def action_focus_mood(self) -> None:
        self.query_one("#mood", Input).focus()

    def action_leave_mood(self) -> None:
        self.set_focus(None)

    def action_pick_model(self) -> None:
        def chosen(model: str | None) -> None:
            self.shell.model = model
            self._show_model()

        self.push_screen(ModelPicker(self.shell), chosen)

    # ------------------------------------------------------------ saved prompts
    @staticmethod
    def palette_actions() -> list[tuple[str, str, str]]:
        """(title, help, action) of every action, for the command palette: all of them, keyed or not."""
        return [
            ("Play / pause", "Pause or resume the music (space)", "toggle"),
            ("Next piece", "A new piece with the same mood (n)", "next"),
            ("Describe a mood", "Type a feeling, a concept or a place (/)", "focus_mood"),
            ("Pick the model", "The model Gentle Shell uses for moods (m)", "pick_model"),
            ("Save what is playing", "Save the prompt and style under a name (s)", "save_preset"),
            ("Saved prompts", "Play or delete a saved prompt (p)", "pick_preset"),
            ("Journey controls", "Restart, skip a stage or stop the journey (j)", "journey_menu"),
            ("Journeys", "Pick, create, open, show, delete or play a journey (J)", "journey_picker"),
            ("Edit the journey", "Change the running journey in words, keeping your place (j)", "journey_edit"),
            ("Save the journey as", "Save the running journey, with its edits, under a name (j)", "journey_save_as"),
            ("Open a journey file", "Validate a JSON journey file, then play or save it (J)", "journey_open"),
            ("Volume up", "Five steps louder (+)", "volume(5)"),
            ("Volume down", "Five steps quieter (-)", "volume(-5)"),
            ("Live controls", "Glide tempo, energy, brightness, space, swing, vinyl, melody density or voice (c)",
             "controls"),
            ("Binaural", "Turn the binaural layer on or off, or glide its carrier, beat and level (B)", "binaural"),
            ("Say a phrase", "Speak a phrase over the music, choosing voice, rate and effect (t)", "say"),
            ("Voices and samples", ("Add, list or remove voice packs; install the FreePats choir or the FluidR3_GM "
                                    "soundfont (v)"), "voices"),
            ("Render to a file", "Render the style playing now or a journey into a WAV file (w)", "render"),
            ("Mute here", "Silence the speakers; a broadcast or a recording keeps the sound (M)", "mute"),
            ("Live broadcast", "Broadcast to YouTube Live or any RTMP(S) ingest; set its URL and stream key (L)",
             "broadcast"),
            ("Record the session", "Start or stop recording what you hear into a WAV file (r)", "record"),
            ("Back", "Leave the app, the music keeps playing (b)", "back"),
            ("Quit", "Leave the app and stop the music (q)", "quit"),
        ]

    def action_controls(self) -> None:
        """Glide the continuous fields, as `ctl tempo` and `ctl glide` do."""
        current = self.player.journey_current()
        driven = Journey.from_dict(current).fields if current is not None else ()

        def applied(result: dict | None) -> None:
            if result:
                changes = ", ".join(f"{name} {value:g}" for name, value in result["fields"].items())
                self._status(f"Gliding {escape(changes)} over {result['over']:g} s")

        self.push_screen(ControlsModal(self.player, self.player.now.style, driven), applied)

    def action_binaural(self) -> None:
        """The binaural layer, as `ctl binaural on|set|off` does."""
        def done(outcome: str | None) -> None:
            if outcome:
                setting = self.player.binaural
                self._status(f"Binaural {outcome}" + (f": {escape(binaural_line(setting))}" if setting else ""))

        self.push_screen(BinauralModal(self.player, self.player.binaural), done)

    def action_say(self) -> None:
        """Say a phrase, as `ctl say` does."""
        def said(result: tuple[str, list[str]] | None) -> None:
            if result is not None:
                phrase, warnings = result
                extra = "".join(f" · warning: {escape(w)}" for w in warnings)
                self._status(f"Saying “{escape(phrase)}” at the next phrase boundary{extra}")

        self.push_screen(SayModal(self.player), said)

    def action_voices(self) -> None:
        """Voice packs and the downloads, as `voices`, `setup-voices` and `setup-samples` do."""
        self.push_screen(VoicesModal())

    def action_render(self) -> None:
        """Render to a WAV file, as `gentle-stream render` does."""
        def done(line: str | None) -> None:
            if line:
                self._status(escape(line))

        self.push_screen(RenderModal(self.player.now.style), done)

    def action_mute(self) -> None:
        """Silence the speakers or bring them back, as `ctl mute` / `ctl unmute`."""
        muted = not self.player.muted
        self.player.set_muted(muted)
        self._status("Muted here; a broadcast or a recording keeps the sound" if muted else "Sound back here")

    def action_broadcast(self) -> None:
        """The live broadcast, as `gentle-stream stream` and `ctl stream start|stop` do."""
        def done(message: str | None) -> None:
            if message:
                self._status(escape(message))

        self.push_screen(BroadcastModal(self.player), done)

    def action_record(self) -> None:
        """Start recording (asks for the file) or stop and say where it was saved."""
        if self.player.recording is not None:
            saved = self.player.record_stop()
            if saved is not None:
                self._status(f"Saved {format_time(saved[1])} to {escape(str(saved[0]))}")
            return

        def started(path: str | None) -> None:
            if path is not None:
                self._status(f"Recording to {escape(path)} · r to stop")

        self.push_screen(RecordDialog(self.player), started)

    def action_save_preset(self) -> None:
        style = self.player.now.style  # what is audible, captured before the dialog opens

        def named(name: str | None) -> None:
            if name is None:
                return
            try:
                preset, replaced = self.presets.save(name, style)
            except PresetError as e:
                self._status(f"[$error]Could not save:[/] {escape(str(e))}")
                return
            self._status(f"{'Replaced' if replaced else 'Saved'} “{escape(preset.name)}”")

        self.push_screen(SaveDialog(style.name), named)

    def action_pick_preset(self) -> None:
        def chosen(preset: Preset | None) -> None:
            if preset is None:
                return
            self.workers.cancel_group(self, "interpret")  # a late interpretation must not override the choice
            self.player.set_style(preset.style)
            self._status(f"Up next: [b]{escape(preset.name)}[/b] (saved)")

        self.push_screen(PresetPicker(self.presets), chosen)

    def action_journey_edit(self) -> None:
        """Edit the running journey in words: the stage diff first, applied only on Apply."""
        current, snap = self.player.journey_current(), self.player.now.journey
        if current is None or snap is None:
            self._status("[$error]Journey:[/] no journey is running")
            return

        def edited(journey: Journey | None) -> None:
            if journey is None:
                return
            try:
                self.player.journey_edit(journey.to_dict())
            except (ValueError, ConnectionError) as e:
                self._status(f"[$error]Journey:[/] {escape(str(e))}")
                return
            usage = modal.usage
            if usage:
                self.session_usage = usage if self.session_usage is None else self.session_usage + usage
                self._show_model()
            self._status(f"Edited journey [b]{escape(journey.title or journey.name)}[/b] from the next bar")

        modal = JourneyEditModal(self.shell, current, snap)
        self.push_screen(modal, edited)

    def _save_journey(self, journey: Journey) -> None:
        def named(name: str | None) -> None:
            if name is None:
                return
            try:
                stored, _ = JourneyStore().save(name, journey)
            except JourneyStoreError as e:
                self._status(f"[$error]Journey:[/] {escape(str(e))}")
                return
            self._status(f'Saved journey "{escape(stored)}"')

        self.push_screen(SaveDialog(journey.title or journey.name, "Save the journey as"), named)

    def action_journey_save_as(self) -> None:
        """Save the running journey (with its edits) under a name."""
        current = self.player.journey_current()
        if current is None:
            self._status("[$error]Journey:[/] no journey is running")
            return
        self._save_journey(Journey.from_dict(current))

    def action_journey_open(self) -> None:
        """Open, validate and show a JSON journey file; then play or save it."""
        def opened(result: tuple[Journey, list[str]] | None) -> None:
            if result is None:
                return
            journey, warnings = result

            def act(choice: str | None) -> None:
                if choice == "play":
                    try:
                        self.player.journey_start(journey.to_dict())
                    except (ValueError, ConnectionError) as e:
                        self._status(f"[$error]Journey:[/] {escape(str(e))}")
                        return
                    self._status(f"Journey [b]{escape(journey.title)}[/b] starts at the next bar")
                elif choice == "save":
                    self._save_journey(journey)

            self.push_screen(JourneyShowModal(journey, warnings, actions=True), act)

        self.push_screen(JourneyFileModal(), opened)

    def action_journey_menu(self) -> None:
        def chosen(action: str | None) -> None:
            if not action:
                return
            if action == "edit":
                self.action_journey_edit()
                return
            if action == "save":
                self.action_journey_save_as()
                return
            try:
                if action == "restart":
                    self.player.journey_restart()
                elif action == "skip":
                    self.player.journey_skip()
                else:
                    self.player.journey_stop()
                self._tick()
            except ValueError as e:
                self._status(f"[$error]Journey:[/] {escape(str(e))}")

        self.push_screen(JourneyMenu(), chosen)

    def action_journey_picker(self, highlight: str | None = None) -> None:
        store = JourneyStore()

        def chosen(choice: str | None) -> None:
            if not choice:
                return
            if choice == "create":
                modal = JourneyPromptModal(self.shell, store)
                self.push_screen(modal, lambda name: created(name, modal.usage))
                return
            if choice == "open":
                self.action_journey_open()
                return
            kind, _, name = choice.partition(":")
            journey = BUILTIN.get(name) if kind == "builtin" else store.get(name)
            if journey is None:
                self._status(f"[$error]Journey:[/] {escape(store.error or name)}")
                return
            try:
                self.player.journey_start(journey.to_dict())
            except (ValueError, ConnectionError) as e:
                self._status(f"[$error]Journey:[/] {escape(str(e))}")
                return
            self._status(f"Journey [b]{escape(journey.title)}[/b] ({escape(name)}) starts at the next bar")
            self._tick()

        def created(name: str | None, usage: Usage | None) -> None:
            if name is None:
                return
            cost = f" · {usage.format()}" if usage else ""
            self._status(f"Saved journey “{escape(name)}”{cost}")
            if usage:
                self.session_usage = usage if self.session_usage is None else self.session_usage + usage
                self._show_model()
            self.action_journey_picker(f"saved:{name}")   # back to the picker, on the new journey

        self.push_screen(JourneyPickerModal(store, highlight), chosen)

    # ------------------------------------------------------------ mood interpretation
    def on_input_submitted(self, event: Input.Submitted) -> None:
        mood = event.value.strip()
        event.input.value = ""
        self.set_focus(None)
        if mood:
            self._request(mood)

    def _request(self, mood: str) -> None:
        self._status(f"Interpreting “{mood}” with {model_label(self.shell.model)}…")
        self._interpret(mood)

    @work(thread=True, exclusive=True, group="interpret")
    def _interpret(self, mood: str) -> None:
        worker = get_current_worker()
        try:
            style, usage = self.shell.interpret_with_usage(mood, self.player.style)
        except InterpretError as e:
            if not worker.is_cancelled:
                self.call_from_thread(self._status, f"[$error]Could not interpret the mood:[/] {escape(str(e))}")
            return
        if worker.is_cancelled:
            return
        self.player.set_style(style)
        self.call_from_thread(self._interpreted, style, usage)

    def _interpreted(self, style: Style, usage: Usage | None) -> None:
        cost = f" · {usage.format()}" if usage else ""
        self._status(f"Up next: [b]{escape(style.name)}[/b] · {escape(style.summary())}{cost}")
        if usage:
            self.session_usage = usage if self.session_usage is None else self.session_usage + usage
            self._show_model()
