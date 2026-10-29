"""The one-line descriptions the TUI and the broadcast picture share."""
from __future__ import annotations

from .binaural import Binaural
from .journey import JourneySnapshot


def format_time(seconds: float) -> str:
    """`m:ss`, clamped to zero: rounding or a cycle boundary can otherwise show a stray negative second."""
    total = max(0, round(seconds))
    return f"{total // 60}:{total % 60:02d}"


DRUM_LABELS = {"none": "no drums", "soft": "soft drums", "busy": "busy drums"}   # "lofi": the genre's own pattern


def details_line(style) -> str:
    """`synthwave · D minor · 106.3 bpm · 1-6-3-7 · brassy polysynth stabs · bright saw lead · drums`: the style with
    its chords, lead and drums named as the genre playing them sounds (its `voices`), not by the shared field names
    (`piano/piano · drums lofi` read as lo-fi words over a synthwave stage)."""
    from .genres import get

    voices = get(style.genre).voices

    def sounds(name: str, part: int) -> str:
        meaning = voices.get(name, name)
        return meaning.split(" / ")[part] if " / " in meaning else meaning

    lead = "no lead" if style.lead == "none" else sounds(style.lead, -1)
    drums = DRUM_LABELS.get(style.drums) or ("lofi drums" if style.genre == "lofi" else "drums")
    return (f"{style.genre} · {style.key} {style.mode} · {style.bpm:g} bpm · "
            f"{'-'.join(str(d) for d in style.progression)} · {sounds(style.chords, 0)} · {lead} · {drums}")


def title_line(style, snap: JourneySnapshot | None) -> str:
    """The title: `♪ Train · Calentamiento lofi` (the journey and its stage) while a journey plays, since the style's
    own name is only the one the music started from; `♪ Midnight Rain` (the style) otherwise."""
    if snap is not None:
        return f"♪ {snap.title} · {snap.stage_name}" if snap.stage_name else f"♪ {snap.title}"
    return f"♪ {style.name}"


def journey_line(snap: JourneySnapshot | None, into_bar: float = 0.0) -> str:
    """`Journey: Warm-up · stage 2/3 "Rise" · 62% · 84 → 100 bpm · 6:40 left`, or "" without a journey. The tempo
    shows one value when the stage ends where it is; `sustaining` replaces the time left once a sustaining journey
    holds its final values. `into_bar` seconds of the audible bar have played (the snapshot is of its start)."""
    if snap is None:
        return ""
    bpm, target = round(snap.bpm), round(snap.target_bpm)
    tempo = f"{bpm} bpm" if bpm == target else f"{bpm} → {target} bpm"
    if snap.open:              # the stage lasts until the listener moves on
        left = "open"
    elif snap.open_ahead:      # a later stage does: no end time yet
        left = "open-ended"
    else:
        left = "sustaining" if snap.seconds_left is None else f"{format_time(snap.seconds_left - into_bar)} left"
    line = (f"Journey: {snap.title} · stage {snap.stage}/{snap.stages} \"{snap.stage_name}\" · "
            f"{round(snap.progress * 100)}% · {tempo} · {left}")
    if snap.override is not None:   # a mood adjusting the journey's fields for the rest of the stage
        name, offsets = snap.override
        changes = ", ".join(f"{field} {delta:+.0f}" if field == "bpm" else f"{field} {delta:+.2f}"
                            for field, delta in sorted(offsets.items()))
        line += f' · mood "{name}": {changes} until "{snap.stage_name}" ends'
    return line


def binaural_line(setting: Binaural | None) -> str:
    """`Binaural: 200 Hz carrier · 6 Hz beat · 5% · headphones recommended`, or "" when the layer is off."""
    if setting is None:
        return ""
    level = round(setting.level * 100, 1)
    return (f"Binaural: {setting.carrier:g} Hz carrier · {setting.beat:g} Hz beat · {level:g}% · "
            "headphones recommended")
