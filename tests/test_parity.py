"""PM-044: every CLI command and `ctl` action has its TUI action, or a stated reason it has none.

The commands come from the parser `gentle-stream` itself uses, so a new command fails here until it is mapped.
"""
import argparse

import pytest

from gentle_stream import build_parser
from gentle_stream.app import NOT_IN_TUI, PARITY, StreamApp


def commands(parser: argparse.ArgumentParser) -> set[str]:
    """`render`, `ctl say`, `journey play`, ...: the top-level commands, with the `ctl` actions and the
    subcommands of the commands that have them."""
    found = set()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    for name, command in sub.choices.items():
        nested = [a for a in command._actions if isinstance(a, argparse._SubParsersAction)]
        actions = [a for a in command._actions if a.dest == "action" and a.choices]
        if nested:
            found |= {f"{name} {inner}" for inner in nested[0].choices}
        elif actions:
            found |= {f"{name} {choice}" for choice in actions[0].choices}
        else:
            found.add(name)
    return found


def unmapped(parser: argparse.ArgumentParser) -> set[str]:
    return commands(parser) - PARITY.keys() - NOT_IN_TUI.keys()


def test_the_walk_finds_the_cli_commands():
    found = commands(build_parser())
    assert {"render", "setup-samples", "setup-voices", "ctl say", "ctl status", "journey play", "voices add"} <= found
    assert "ctl" not in found and "journey" not in found


def test_every_cli_command_has_a_tui_action_or_a_stated_reason():
    assert unmapped(build_parser()) == set(), "map these in gentle_stream.app.PARITY (or NOT_IN_TUI, with why)"
    assert set(PARITY) | set(NOT_IN_TUI) == commands(build_parser()), "entries for commands the CLI no longer has"
    assert not set(PARITY) & set(NOT_IN_TUI)
    assert all(reason.strip() for reason in NOT_IN_TUI.values())


def test_every_mapped_action_exists_and_is_in_the_palette():
    palette = {action for _, _, action in StreamApp.palette_actions()}
    for command, action in PARITY.items():
        assert callable(getattr(StreamApp, f"action_{action}", None)), command
        assert action in palette, command


def test_removing_an_entry_fails_the_guard(monkeypatch):
    monkeypatch.delitem(PARITY, "render")
    assert unmapped(build_parser()) == {"render"}


def test_a_new_cli_command_fails_the_guard_until_it_is_mapped():
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    sub.add_parser("frobnicate")
    assert unmapped(parser) == {"frobnicate"}


def test_build_parser_is_the_parser_main_uses(capsys):
    from gentle_stream import main

    with pytest.raises(SystemExit):
        main(["--help"])
    assert capsys.readouterr().out == build_parser().format_help()
