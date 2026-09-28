"""Compose terminal frames and define iterator auto-scroll policies.

``AutoScrollMode`` is ``"smart"`` when manual upward movement suspends
following, or ``"strict"`` when every new batch follows the bottom.
"""

from __future__ import annotations

from os import terminal_size
from shutil import get_terminal_size
from sys import stdout
from typing import TYPE_CHECKING, Literal

from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.panel_layout import allocate_panel_heights
from tuiloom.render.segment_diff import SegmentChange, get_segment_changes
from tuiloom.render.terminal_text import clip_display, display_width, normalize_line
from tuiloom.render.viewport import Viewport
from tuiloom.screen_content import ContentSize

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
        content_spacing: bool,
    ) -> None:
        self._menu = menu
        self._menu_renderer = menu_renderer
        self._content_spacing = content_spacing
        self._previous_lines: list[str] | None = None
        self._previous_terminal_size: terminal_size | None = None
        self._last_render_key: tuple[object, ...] | None = None

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
                    panel,
                    panel._renderer,
                    self._menu._visible_panel_description(panel),
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
        menu_lines = self._menu_renderer.render(
            max_width=terminal_width - 2
        ).splitlines() or [""]
        menu_height = len(menu_lines)
        menu_width = max(display_width(line) for line in menu_lines)
        panels = self._menu._visible_content_panels()
        if menu_width > terminal_width or menu_height > terminal_height:
            return self._render_terminal_too_small()
        if not panels:
            return [normalize_line(line) for line in menu_lines]

        spacing = 1 if self._content_spacing else 0
        viewport_width = terminal_width - 2
        panel_total = terminal_height - menu_height - spacing
        if viewport_width <= 0:
            return self._render_terminal_too_small()
        heights = allocate_panel_heights(panels, panel_total)
        if heights is None:
            return self._render_terminal_too_small()
        show_labels = len(panels) > 1 or self._menu._task_exit is not None
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
                    self._menu._visible_panel_description(panel)
                    if show_labels
                    else None,
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
        content = panel.content
        effective_size = ContentSize(
            width=max(width, content.min_width or width),
            height=max(height, content.min_height or height),
        )
        loop = self._menu._event_loop
        if loop is not None:
            loop.update_content_panel_size(panel, effective_size)
        else:
            panel._effective_size = effective_size
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

    def apply_stream_auto_scroll(
        self,
        mode: AutoScrollMode | None,
        panel: ContentPanel,
    ) -> None:
        """Apply or defer iterator following for one panel batch."""
        if mode is None:
            panel._pending_auto_scroll = None
            return
        if mode == "smart" and not panel._smart_auto_scroll_active:
            return
        panel._pending_auto_scroll = mode
        if panel._viewport is not None:
            panel._viewport.scroll_to_bottom()

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
