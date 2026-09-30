"""Explicit selectable rows and their UI-thread activation context."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tuiloom.key_binding import KeyBinding

if TYPE_CHECKING:
    from tuiloom.content_panel import ContentPanel
    from tuiloom.terminal_app import TerminalApp
    from tuiloom.terminal_menu import TerminalMenu


@dataclass(frozen=True, slots=True)
class SelectableItem:
    """One visible panel row with an application-defined value and optional action.

    Attributes:
        content: One terminal text row, supporting safe ANSI SGR and Unicode.
        value: Opaque application payload; Tuiloom never interprets it.
        key: Optional unique hashable identity used to restore selection after
            a source replacement. Equal keys within one source are rejected.
        enabled: Disabled rows remain visible but cannot be selected or activated.
        on_activate: Optional UI-thread callback receiving `SelectableContext`.
            Return values are ignored; exceptions propagate through the loop.
    """

    content: str
    value: object = None
    key: Hashable | None = None
    enabled: bool = True
    on_activate: Callable[[SelectableContext], None] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise TypeError("SelectableItem content must be a str")
        if not isinstance(self.enabled, bool):
            raise TypeError("SelectableItem enabled must be a bool")
        if self.on_activate is not None and not callable(self.on_activate):
            raise TypeError("SelectableItem on_activate must be callable or None")
        if self.key is not None:
            hash(self.key)


@dataclass(frozen=True, slots=True)
class SelectableContext:
    """Describe an item activated from a focused content panel.

    The immutable fields expose the application, menu, panel, selected item,
    its opaque value, zero-based item index (excluding plain rows), and
    triggering binding. They refer to live objects rather than copies.
    """

    app: TerminalApp
    menu: TerminalMenu
    panel: ContentPanel
    item: SelectableItem
    value: object
    index: int
    binding: KeyBinding | None


type SelectableCallback = Callable[[SelectableContext], None]
