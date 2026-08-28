"""Callback aliases, execution contexts, and stable command handles.

``CommandBehavior`` is a callback receiving :class:`CommandContext`.
``InputBehavior`` receives the submitted Unicode text from free-form input.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tuiloom.key_binding import KeyBinding

if TYPE_CHECKING:
    from tuiloom.terminal_app import TerminalApp
    from tuiloom.terminal_menu import TerminalMenu


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Describe one callback execution created by Tuiloom.

    Attributes:
        app: Application dispatching the callback.
        menu: Menu active when the callback was dispatched.
        command: Stable menu/global handle, or ``None`` for alert confirmation.
        binding: Triggering binding, or ``None`` for programmatic execution.
    """

    app: TerminalApp
    menu: TerminalMenu
    command: MenuCommand | GlobalCommand | None
    binding: KeyBinding | None


type CommandBehavior = Callable[[CommandContext], None]
type InputBehavior = Callable[[str], None]


class MenuCommand:
    """Stable handle for one selectable menu command.

    Attributes:
        label: Current visible label.
        behavior: Current callback.
        position: Zero-based position among user commands.
        enabled: Whether the command can currently be selected and activated.
    """

    __slots__ = ("_menu", "_label", "_behavior", "_enabled")

    def __init__(
        self, menu: TerminalMenu, label: str, behavior: CommandBehavior
    ) -> None:
        self._menu = menu
        self._label = label
        self._behavior = behavior
        self._enabled = True

    @property
    def label(self) -> str:
        """Return the command's current label."""
        return self._label

    @property
    def behavior(self) -> CommandBehavior:
        """Return the command's current callback."""
        return self._behavior

    @property
    def position(self) -> int:
        """Return the command's current zero-based position."""
        return self._menu._position_of(self)

    @property
    def enabled(self) -> bool:
        """Return whether the command is locally enabled."""
        return self._enabled


class GlobalCommand:
    """Stable handle and read-only metadata for one invisible global command.

    Attributes:
        binding: Binding that immediately invokes the command.
        label: User-defined label suitable for a custom help display.
        behavior: Application-level callback.
    """

    __slots__ = ("_app", "_binding", "_label", "_behavior")

    def __init__(
        self,
        app: TerminalApp,
        binding: KeyBinding,
        label: str,
        behavior: CommandBehavior,
    ) -> None:
        self._app = app
        self._binding = binding
        self._label = label
        self._behavior = behavior

    @property
    def binding(self) -> KeyBinding:
        """Return the current triggering binding."""
        return self._binding

    @property
    def label(self) -> str:
        """Return the descriptive label."""
        return self._label

    @property
    def behavior(self) -> CommandBehavior:
        """Return the application-level callback."""
        return self._behavior


def _without_context(action: Callable[[], None]) -> CommandBehavior:
    """Adapt an internal zero-argument action to a command callback."""

    def wrapped(context: CommandContext) -> None:
        action()

    return wrapped
