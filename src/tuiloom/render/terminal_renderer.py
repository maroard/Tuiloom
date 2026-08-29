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
from tuiloom.render.terminal_text import clip_display, display_width, normalize_line
from tuiloom.render.viewport import Viewport

if TYPE_CHECKING:
    from tuiloom.content_panel import ContentPanel
    from tuiloom.terminal_menu import TerminalMenu

type AutoScrollMode = Literal["smart", "strict"]
type ScrollDirection = Literal["up", "down", "left", "right"]


class TerminalRenderer:
    """Compose independently focusable content panels and the menu box."""

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
        primary = menu._primary_content_panel
        if primary is not None:
            primary._renderer = content_renderer
        self._content_spacing = content_spacing
        self._previous_lines: list[str] | None = None
        self._previous_terminal_size: terminal_size | None = None
        self._last_render_key: tuple[object, ...] | None = None

    @property
    def viewport(self) -> Viewport | None:
        """Return the primary viewport as a compatibility reference."""
        primary = self._menu._primary_content_panel
        return primary._viewport if primary is not None else None

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
            tuple(
                (
                    panel._renderer.rendered_content.revision,
                    panel._viewport.offset_x if panel._viewport is not None else 0,
                    panel._viewport.offset_y if panel._viewport is not None else 0,
                )
                for panel in self._menu._visible_content_panels()
            ),
            self._menu_renderer.revision,
            self._content_spacing,
        )

    def _compose_frame(self, terminal_width: int, terminal_height: int) -> list[str]:
        if not self._menu.show:
            return [""]
        menu_lines = self._menu_renderer.render().splitlines() or [""]
        menu_height = len(menu_lines)
        menu_width = max(display_width(line) for line in menu_lines)
        panels = self._menu._visible_content_panels()
        if menu_width > terminal_width or menu_height > terminal_height:
            return self._render_terminal_too_small()
        if not panels:
            return [normalize_line(line) for line in menu_lines]

        spacing = 1 if self._content_spacing else 0
        viewport_width = terminal_width - 2
        inner_total = terminal_height - menu_height - spacing - 2 * len(panels)
        if viewport_width <= 0 or inner_total < len(panels):
            return self._render_terminal_too_small()
        base_height, remainder = divmod(inner_total, len(panels))
        heights = [
            base_height + (1 if index < remainder else 0)
            for index in range(len(panels))
        ]
        show_labels = len(panels) > 1
        content_lines: list[str] = []
        for panel, height in zip(panels, heights, strict=True):
            self._update_viewport(panel, viewport_width, height)
            focused = (
                self._menu._focused_panel is panel and self._menu._alert_text is None
            )
            horizontal = "─" if focused else "┄"
            vertical = "│" if focused else "┊"
            content_lines.append(
                self._panel_top_border(
                    viewport_width,
                    horizontal,
                    panel.description if show_labels else None,
                )
            )
            viewport = panel._viewport
            if viewport is None:
                raise RuntimeError("Content panel viewport was not initialized")
            content_lines.extend(
                f"{vertical}{line}{vertical}" for line in viewport.render().split("\n")
            )
            content_lines.append(f"╰{horizontal * viewport_width}╯")
        return [
            normalize_line(line)
            for line in content_lines + ([""] * spacing) + menu_lines
        ]

    def _update_viewport(
        self,
        panel: ContentPanel,
        width: int,
        height: int,
    ) -> None:
        rendered = panel._renderer.update()
        if panel._viewport is None:
            panel._viewport = Viewport(rendered, width, height)
        else:
            panel._viewport.content = rendered
            panel._viewport.width = width
            panel._viewport.height = height
        self._apply_panel_auto_scroll(panel)

    @staticmethod
    def _panel_top_border(
        width: int,
        horizontal: str,
        label: str | None,
    ) -> str:
        if not label or width < 5:
            return f"╭{horizontal * width}╮"
        clipped = clip_display(label, 0, width - 4)
        prefix = f"{horizontal} {clipped} "
        return f"╭{prefix}{horizontal * (width - display_width(prefix))}╮"

    @staticmethod
    def _apply_panel_auto_scroll(panel: ContentPanel) -> None:
        pending = panel._pending_auto_scroll
        viewport = panel._viewport
        if pending is None or viewport is None:
            return
        panel._pending_auto_scroll = None
        if pending == "strict" or panel._smart_auto_scroll_active:
            viewport.scroll_to_bottom()

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
        """Replace the primary renderer and reset its viewport."""
        self._content_renderer = content_renderer
        primary = self._menu._primary_content_panel
        if primary is not None:
            primary._renderer = content_renderer
            primary._viewport = None
            self.reset_stream_auto_scroll(primary)
        self.invalidate()

    def apply_stream_auto_scroll(
        self,
        mode: AutoScrollMode | None,
        panel: ContentPanel | None = None,
    ) -> None:
        """Apply or defer iterator following for one panel batch."""
        panel = panel or self._menu._primary_content_panel
        if panel is None:
            return
        if mode is None:
            panel._pending_auto_scroll = None
            return
        if mode == "smart" and not panel._smart_auto_scroll_active:
            return
        panel._pending_auto_scroll = mode
        if panel._viewport is not None:
            panel._viewport.scroll_to_bottom()

    def reset_stream_auto_scroll(self, panel: ContentPanel | None = None) -> None:
        """Reset smart-follow state for one newly installed source."""
        panel = panel or self._menu._primary_content_panel
        if panel is None:
            return
        panel._smart_auto_scroll_active = True
        panel._pending_auto_scroll = None

    def scroll_panel(self, panel: ContentPanel, direction: ScrollDirection) -> None:
        """Scroll one panel and update its smart-follow state."""
        viewport = panel._viewport
        if viewport is None:
            return
        previous_y = viewport.offset_y
        getattr(viewport, f"scroll_{direction}")()
        if direction == "up" and viewport.offset_y < previous_y:
            panel._smart_auto_scroll_active = False
        elif direction == "down" and viewport.is_at_bottom():
            panel._smart_auto_scroll_active = True

    def scroll_up(self) -> None:
        """Move the focused or primary content one row up."""
        panel = self._menu._focused_panel or self._menu._primary_content_panel
        if panel is not None:
            self.scroll_panel(panel, "up")

    def scroll_down(self) -> None:
        """Move the focused or primary content one row down."""
        panel = self._menu._focused_panel or self._menu._primary_content_panel
        if panel is not None:
            self.scroll_panel(panel, "down")

    def scroll_left(self) -> None:
        """Move the focused or primary content one column left."""
        panel = self._menu._focused_panel or self._menu._primary_content_panel
        if panel is not None:
            self.scroll_panel(panel, "left")

    def scroll_right(self) -> None:
        """Move the focused or primary content one column right."""
        panel = self._menu._focused_panel or self._menu._primary_content_panel
        if panel is not None:
            self.scroll_panel(panel, "right")
