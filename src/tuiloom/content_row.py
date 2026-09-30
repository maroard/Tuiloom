"""A menu-owned row of content panels."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuiloom.content_panel import ContentPanel
    from tuiloom.terminal_menu import TerminalMenu


class ContentRow:
    """Expose one row of panels in a menu's content layout."""

    __slots__ = ("_menu", "_panels", "_active")

    def __init__(self, menu: TerminalMenu, panels: tuple[ContentPanel, ...]) -> None:
        self._menu = menu
        self._panels = panels
        self._active = True

    @property
    def panels(self) -> tuple[ContentPanel, ...]:
        """Return the panels in this row from left to right."""
        return self._panels

    @property
    def collapsed(self) -> bool:
        """Report whether the complete row uses fixed collapsed height."""
        return self._panels[0].collapsed

    @property
    def collapsed_height(self) -> int:
        """Return the row's configured collapsed content height."""
        return self._panels[0].collapsed_height

    def collapse(self) -> None:
        """Collapse every panel in this row as one vertical unit."""
        self._menu._set_content_row_collapsed(self, True)

    def expand(self) -> None:
        """Expand every panel in this row as one vertical unit."""
        self._menu._set_content_row_collapsed(self, False)

    def toggle_collapse(self) -> None:
        """Switch the complete row between fixed and weighted height."""
        self._menu._set_content_row_collapsed(self, not self.collapsed)

    def set_collapsed_height(self, height: int) -> None:
        """Set one fixed content height for every panel in this row."""
        self._menu._set_content_row_collapsed_height(self, height)
