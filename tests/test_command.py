from dataclasses import FrozenInstanceError

import pytest

from tuiloom import (
    Command,
    CommandBehavior,
    CommandContext,
    CommandDict,
    ScreenContext,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.command import _without_context


def test_command_context_is_frozen_slotted_execution_data() -> None:
    app = TerminalApp("Example")
    menu = TerminalMenu(app, ScreenContext("Example", "Menu", "Menu"))
    context = CommandContext(app=app, menu=menu, command_key="1")

    assert context.app is app
    assert context.menu is menu
    assert context.command_key == "1"
    assert not hasattr(context, "__dict__")
    with pytest.raises(FrozenInstanceError):
        context.command_key = "2"  # type: ignore[misc]


def test_public_command_aliases_describe_one_context_callback() -> None:
    contexts: list[CommandContext] = []
    behavior: CommandBehavior = contexts.append
    command: Command = (behavior, "Capture")
    commands: CommandDict = {"1": command}

    assert commands["1"] == (behavior, "Capture")


def test_without_context_ignores_the_execution_context() -> None:
    app = TerminalApp("Example")
    menu = TerminalMenu(app, ScreenContext("Example", "Menu", "Menu"))
    calls: list[str] = []
    wrapped = _without_context(lambda: calls.append("called"))

    wrapped(CommandContext(app=app, menu=menu, command_key="1"))

    assert calls == ["called"]
