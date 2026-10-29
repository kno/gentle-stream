"""The one-line descriptions the TUI and the broadcast picture share."""
from __future__ import annotations

from .binaural import Binaural
from .journey import JourneySnapshot


def format_time(seconds: float) -> str:
    """`m:ss`, clamped to zero: rounding or a cycle boundary can otherwise show a stray negative second."""
    total = max(0, round(seconds))
    return f"{total // 60}:{total % 60:02d}"


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
