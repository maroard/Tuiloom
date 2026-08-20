from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuiloom.terminal_app import TerminalApp
    from tuiloom.terminal_menu import TerminalMenu


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Describe one command execution created by Tuiloom.

    The context exposes the active application, originating menu, and resolved
    registry key to the user callback handling that execution.
    """

    app: TerminalApp
    menu: TerminalMenu
    command_key: str


type CommandBehavior = Callable[[CommandContext], None]
type InputBehavior = Callable[[str], None]
type Command = tuple[CommandBehavior, str]
type CommandDict = dict[str, Command]


def _without_context(action: Callable[[], None]) -> CommandBehavior:
    """Adapt an internal zero-argument action to a command callback."""

    def wrapped(context: CommandContext) -> None:
        action()

    return wrapped
