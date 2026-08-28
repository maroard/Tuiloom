"""Compose terminal frames and define iterator auto-scroll policies.

``AutoScrollMode`` is ``"smart"`` when manual upward movement suspends
following, or ``"strict"`` when every new batch follows the bottom.
"""

from __future__ import annotations

from os import terminal_size
from shutil import get_terminal_size
from sys import stdout
from typing import TYPE_CHECKING, Literal

from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.segment_diff import SegmentChange, get_segment_changes
from tuiloom.render.terminal_text import display_width, normalize_line
from tuiloom.render.viewport import Viewport

if TYPE_CHECKING:
    from tuiloom.terminal_menu import TerminalMenu

type AutoScrollMode = Literal["smart", "strict"]


class TerminalRenderer:
    """Compose focused content and menu boxes and update the terminal."""

    def __init__(
        self,
        *,
        menu: TerminalMenu,
        menu_renderer: MenuRenderer,
        content_renderer: ContentRenderer,
        content_spacing: bool,
    ) -> None:
        self._menu = menu
        self._menu_renderer = menu_renderer
        self._content_renderer = content_renderer
        self._content_spacing = content_spacing
        self._viewport: Viewport | None = None
        self._previous_lines: list[str] | None = None
        self._previous_terminal_size: terminal_size | None = None
        self._last_render_key: tuple[object, ...] | None = None
        self._smart_auto_scroll_active = True
        self._pending_auto_scroll: AutoScrollMode | None = None

    @property
    def viewport(self) -> Viewport | None:
        """Return the active content viewport as a read-only reference."""
        return self._viewport

    def render(self, input_buffer: str = "") -> None:
        """Render and write one complete terminal frame."""
        self._menu_renderer.update()
        current_size = get_terminal_size()
        render_key = self._get_render_key(current_size)
        if render_key == self._last_render_key:
            return
        lines = self._compose_frame(current_size.columns, current_size.lines)
        if self._previous_lines is None or self._previous_terminal_size != current_size:
            self._write_full_frame(lines)
        else:
            changes = get_segment_changes(self._previous_lines, lines)
            if changes:
                self._write_segment_changes(changes)
        self._restore_cursor(lines)
        stdout.flush()
        self._previous_lines = lines
        self._previous_terminal_size = current_size
        self._last_render_key = render_key

    def _get_render_key(self, current_size: terminal_size) -> tuple[object, ...]:
        return (
            current_size,
            self._content_renderer.rendered_content.revision,
            self._menu_renderer.revision,
            self._content_spacing,
            self._viewport.offset_x if self._viewport else 0,
            self._viewport.offset_y if self._viewport else 0,
        )

    def _compose_frame(self, terminal_width: int, terminal_height: int) -> list[str]:
        if not self._menu.show:
            return [""]
        menu_render = self._menu_renderer.render()
        menu_lines = menu_render.splitlines() or [""]
        menu_height = len(menu_lines)
        menu_width = max(display_width(line) for line in menu_lines)
        has_content = self._menu._has_content()
        if menu_width > terminal_width or menu_height > terminal_height:
            return self._render_terminal_too_small()
        if not has_content:
            self._viewport = None
            return [normalize_line(line) for line in menu_lines]

        spacing = 1 if self._content_spacing else 0
        viewport_width = terminal_width - 2
        viewport_height = terminal_height - menu_height - spacing - 2
        if viewport_width <= 0 or viewport_height <= 0:
            return self._render_terminal_too_small()
        rendered_content = self._content_renderer.update()
        if self._viewport is None:
            self._viewport = Viewport(rendered_content, viewport_width, viewport_height)
        else:
            self._viewport.content = rendered_content
            self._viewport.width = viewport_width
            self._viewport.height = viewport_height
        self._apply_pending_auto_scroll()
        focused = self._menu._focus == "content" and self._menu._alert_text is None
        horizontal = "─" if focused else "┄"
        vertical = "│" if focused else "┊"
        content_lines = [f"╭{horizontal * viewport_width}╮"]
        content_lines.extend(
            f"{vertical}{line}{vertical}"
            for line in self._viewport.render().split("\n")
        )
        content_lines.append(f"╰{horizontal * viewport_width}╯")
        return [
            normalize_line(line)
            for line in content_lines + ([""] * spacing) + menu_lines
        ]

    def _apply_pending_auto_scroll(self) -> None:
        if self._pending_auto_scroll is None or self._viewport is None:
            return
        mode = self._pending_auto_scroll
        self._pending_auto_scroll = None
        if mode == "strict" or self._smart_auto_scroll_active:
            self._viewport.scroll_to_bottom()

    @staticmethod
    def _render_terminal_too_small() -> list[str]:
        return ["Terminal window is too small."]

    @staticmethod
    def _write_full_frame(lines: list[str]) -> None:
        stdout.write("\033[?25l\033[H\033[J" + "\n".join(lines))

    @staticmethod
    def _write_segment_changes(changes: list[SegmentChange]) -> None:
        stdout.write("\033[?25l")
        for change in changes:
            stdout.write(
                f"\033[{change.row};{change.column}H{normalize_line(change.content)}"
            )
            if change.clear_width:
                stdout.write(f"\033[{change.clear_width}X")

    def _restore_cursor(self, lines: list[str]) -> None:
        if self._menu._input_behavior is None or self._menu._alert_text is not None:
            stdout.write("\033[?25l")
            return
        row = len(lines)
        column = display_width(lines[-1]) + 1
        stdout.write(f"\033[{row};{column}H\033[?25h")

    def invalidate(self) -> None:
        """Force a complete redraw on the next frame."""
        self._previous_lines = None
        self._previous_terminal_size = None
        self._last_render_key = None

    def set_content_renderer(self, content_renderer: ContentRenderer) -> None:
        """Replace content and reset source-specific viewport state."""
        self._content_renderer = content_renderer
        self._viewport = None
        self.reset_stream_auto_scroll()
        self.invalidate()

    def apply_stream_auto_scroll(self, mode: AutoScrollMode | None) -> None:
        """Apply or defer iterator following for one output batch."""
        if mode is None:
            self._pending_auto_scroll = None
            return
        if mode == "smart" and not self._smart_auto_scroll_active:
            return
        self._pending_auto_scroll = mode
        if self._viewport is not None:
            self._viewport.scroll_to_bottom()

    def reset_stream_auto_scroll(self) -> None:
        """Reset smart-follow state for a newly installed source."""
        self._smart_auto_scroll_active = True
        self._pending_auto_scroll = None

    def scroll_up(self) -> None:
        """Move content up and suspend smart following after movement."""
        if self._viewport is not None:
            previous = self._viewport.offset_y
            self._viewport.scroll_up()
            if self._viewport.offset_y < previous:
                self._smart_auto_scroll_active = False

    def scroll_down(self) -> None:
        """Move content down and resume smart following at the bottom."""
        if self._viewport is not None:
            self._viewport.scroll_down()
            if self._viewport.is_at_bottom():
                self._smart_auto_scroll_active = True

    def scroll_left(self) -> None:
        """Move content one column left."""
        if self._viewport is not None:
            self._viewport.scroll_left()

    def scroll_right(self) -> None:
        """Move content one column right."""
        if self._viewport is not None:
            self._viewport.scroll_right()
