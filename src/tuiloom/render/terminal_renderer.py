"""Compose terminal frames and define iterator auto-scroll policies.

``AutoScrollMode`` is ``"smart"`` when manual upward movement suspends
following, or ``"strict"`` when every new batch follows the bottom.
"""

from __future__ import annotations

from math import floor
from os import terminal_size
from shutil import get_terminal_size
from sys import stdout
from typing import TYPE_CHECKING, Literal

from tuiloom.animation import AnimationFrame
from tuiloom.configuration import AutoScrollMode
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.panel_layout import allocate_panel_heights, allocate_panel_widths
from tuiloom.render.rendered_content import RenderResult
from tuiloom.render.segment_diff import SegmentChange, get_segment_changes
from tuiloom.render.terminal_text import (
    clip_display,
    display_width,
    normalize_line,
    overlay_display,
)
from tuiloom.render.viewport import Viewport
from tuiloom.screen_content import ContentSize

if TYPE_CHECKING:
    from tuiloom.content_panel import ContentPanel
    from tuiloom.terminal_menu import TerminalMenu

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
        self._status_key: tuple[object, ...] | None = None
        self._status_line: str | None = None
        self._last_composition: RenderResult | None = None
        self._animation_elapsed = 0.0

    def set_animation_elapsed(self, elapsed: float) -> None:
        """Use a shared menu-time snapshot for animated status rendering."""
        self._animation_elapsed = elapsed

    def render(self, input_buffer: str = "") -> None:
        """Render and write one complete terminal frame."""
        self._menu_renderer.update()
        current_size = get_terminal_size()
        status_line = self._render_status_line(current_size.columns)
        render_key = self._get_render_key(current_size) + (status_line,)
        if render_key == self._last_render_key:
            return
        result = self._compose_result(
            current_size.columns, current_size.lines, status_line
        )
        self._last_composition = result
        lines = result.lines
        if self._previous_lines is None or self._previous_terminal_size != current_size:
            self._write_full_frame(lines)
        else:
            changes = get_segment_changes(self._previous_lines, lines)
            if changes:
                self._write_segment_changes(changes)
        self._restore_cursor(result)
        stdout.flush()
        self._previous_lines = lines
        self._previous_terminal_size = current_size
        self._last_render_key = render_key

    def _get_render_key(self, current_size: terminal_size) -> tuple[object, ...]:
        return (
            current_size,
            tuple(self._menu._visible_content_rows()),
            tuple(
                (
                    panel,
                    panel._runtime.renderer,
                    self._menu._visible_panel_description(panel),
                    panel._runtime.renderer.rendered_content.revision,
                    panel.selected_index,
                    panel._runtime.selection_revision,
                    panel.selection_style,
                    panel._runtime.viewport.offset_x
                    if panel._runtime.viewport is not None
                    else 0,
                    panel._runtime.viewport.offset_y
                    if panel._runtime.viewport is not None
                    else 0,
                    panel.padding_top,
                    panel.padding_bottom,
                    panel.padding_left,
                    panel.padding_right,
                )
                for panel in self._menu._visible_content_panels()
            ),
            self._menu_renderer.revision,
            self._content_spacing,
            self._menu.presentation,
            self._menu.menu_visible,
            self._menu._focused_panel,
        )

    def _render_status_line(self, width: int) -> str | None:
        status = self._menu.status_bar
        if status is None:
            return None
        width = max(0, width)
        index = (
            floor(self._animation_elapsed * status.fps + 1e-9)
            if status._kind == "animated" and status.fps is not None
            else None
        )
        key = (
            status,
            width,
            self._menu._status_bar_revision,
            index,
            self._menu.focused_panel,
        )
        if key != self._status_key or status._kind == "dynamic":
            if status._kind == "animated":
                animated = status._animated_renderer
                if animated is None or index is None:
                    raise RuntimeError("Animated status renderer is missing")
                value = animated(width, AnimationFrame(self._animation_elapsed, index))
            else:
                value = status._producer(width)
            if not isinstance(value, str):
                raise TypeError("StatusBar renderer must return a str")
            self._status_line = clip_display(normalize_line(value), 0, width)
            self._status_key = key
        return self._status_line

    def _compose_frame(self, terminal_width: int, terminal_height: int) -> list[str]:
        return self.compose(terminal_width, terminal_height).lines

    def compose(self, terminal_width: int, terminal_height: int) -> RenderResult:
        """Compose physical frame lines and their optional input cursor."""
        result = self._compose_result(
            terminal_width, terminal_height, self._render_status_line(terminal_width)
        )
        self._last_composition = result
        return result

    def _compose_frame_with_status(
        self, terminal_width: int, terminal_height: int, status_line: str | None
    ) -> list[str]:
        result = self._compose_result(terminal_width, terminal_height, status_line)
        self._last_composition = result
        return result.lines

    def _compose_result(
        self, terminal_width: int, terminal_height: int, status_line: str | None
    ) -> RenderResult:
        if terminal_width <= 0 or terminal_height <= 0:
            return RenderResult([""])
        if status_line is None:
            return self._compose_body(terminal_width, terminal_height)
        available = terminal_height - 1
        body = self._compose_body(terminal_width, available)
        if body.too_small:
            return body
        if available == 0 and body.lines == [""]:
            return RenderResult([status_line])
        return RenderResult(
            body.lines + [""] * (available - len(body.lines)) + [status_line],
            body.cursor,
        )

    def _compose_body(self, terminal_width: int, terminal_height: int) -> RenderResult:
        menu = self._menu_renderer.render_result(max_width=terminal_width - 2)
        menu_lines = menu.lines
        menu_height = len(menu_lines)
        menu_width = max((display_width(line) for line in menu_lines), default=0)
        rows = self._menu._visible_content_rows()
        panels = tuple(panel for row in rows for panel in row)
        overlay = self._menu.presentation == "overlay"
        if menu_width > terminal_width or menu_height > terminal_height:
            return RenderResult(
                self._render_terminal_too_small(terminal_width), too_small=True
            )
        if not panels:
            if overlay:
                return self._compose_overlay([], menu, terminal_width, terminal_height)
            return RenderResult(
                [normalize_line(line) for line in menu_lines] or [""], menu.cursor
            )

        spacing = int(self._content_spacing and bool(menu_lines) and not overlay)
        panel_total = terminal_height - (0 if overlay else menu_height) - spacing
        widths = [allocate_panel_widths(row, terminal_width) for row in rows]
        if any(row_widths is None for row_widths in widths):
            return RenderResult(
                self._render_terminal_too_small(terminal_width), too_small=True
            )
        heights = allocate_panel_heights(rows, panel_total)
        if heights is None:
            return RenderResult(
                self._render_terminal_too_small(terminal_width), too_small=True
            )
        if any(
            viewport_width <= panel.padding_left + panel.padding_right
            or height <= panel.padding_top + panel.padding_bottom
            for row, height, row_widths in zip(rows, heights, widths, strict=True)
            for panel, viewport_width in zip(row, row_widths or (), strict=True)
        ):
            return RenderResult(
                self._render_terminal_too_small(terminal_width), too_small=True
            )
        show_labels = len(panels) > 1 or self._menu._task_exit is not None
        content_lines: list[str] = []
        for row, height, row_widths in zip(rows, heights, widths, strict=True):
            if row_widths is None:
                raise RuntimeError("Panel widths were not allocated")
            fragments: list[list[str]] = []
            for panel, viewport_width in zip(row, row_widths, strict=True):
                self._update_viewport(
                    panel,
                    viewport_width - panel.padding_left - panel.padding_right,
                    height - panel.padding_top - panel.padding_bottom,
                )
                focused = self._menu.focused_panel is panel
                horizontal = "─" if focused else "┄"
                vertical = "│" if focused else "┊"
                top = self._panel_top_border(
                    viewport_width,
                    horizontal,
                    self._menu._visible_panel_description(panel)
                    if show_labels
                    else None,
                )
                viewport = panel._runtime.viewport
                if viewport is None:
                    raise RuntimeError("Content panel viewport was not initialized")
                fragments.append(
                    [top]
                    + [f"{vertical}{' ' * viewport_width}{vertical}"]
                    * panel.padding_top
                    + [
                        normalize_line(
                            f"{vertical}{' ' * panel.padding_left}"
                            f"{line}{' ' * panel.padding_right}{vertical}"
                        )
                        for line in viewport.render().split("\n")
                    ]
                    + [f"{vertical}{' ' * viewport_width}{vertical}"]
                    * panel.padding_bottom
                    + [f"╰{horizontal * viewport_width}╯"]
                )
            content_lines.extend(
                "".join(parts) for parts in zip(*fragments, strict=True)
            )
        if overlay:
            return self._compose_overlay(
                content_lines, menu, terminal_width, terminal_height
            )
        cursor = menu.cursor
        if cursor is not None:
            cursor = (len(content_lines) + spacing + cursor[0], cursor[1])
        return RenderResult(
            [
                normalize_line(line)
                for line in content_lines + ([""] * spacing) + menu_lines
            ],
            cursor,
        )

    def _compose_overlay(
        self,
        background: list[str],
        menu: RenderResult,
        width: int,
        height: int,
    ) -> RenderResult:
        lines = [normalize_line(line) for line in background]
        lines.extend([""] * (height - len(lines)))
        menu_lines = menu.lines
        if not menu_lines:
            return RenderResult(lines or [""])
        menu_width = max(display_width(line) for line in menu_lines)
        x = (width - menu_width) // 2
        y = (height - len(menu_lines)) // 2
        for row, line in enumerate(menu_lines):
            lines[y + row] = overlay_display(lines[y + row], line, x)
        cursor = menu.cursor
        if cursor is not None:
            cursor = (y + cursor[0], x + cursor[1])
        return RenderResult(lines, cursor)

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
            panel._runtime.effective_size = effective_size
        rendered = panel._runtime.renderer.update()
        if panel._runtime.viewport is None:
            panel._runtime.viewport = Viewport(rendered, width, height)
        else:
            if (
                panel._runtime.viewport.width != width
                or panel._runtime.viewport.height != height
            ):
                panel._runtime.selection_visibility_pending = True
            panel._runtime.viewport.content = rendered
            panel._runtime.viewport.width = width
            panel._runtime.viewport.height = height
        self._apply_panel_auto_scroll(panel)
        viewport = panel._runtime.viewport
        viewport.selection_row = panel._selected_row()
        viewport.selection_style = panel.selection_style
        if (
            panel._runtime.selection_visibility_pending
            and viewport.selection_row is not None
        ):
            viewport.ensure_visible(viewport.selection_row)
        panel._runtime.selection_visibility_pending = False

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
        pending = panel._runtime.pending_auto_scroll
        viewport = panel._runtime.viewport
        if pending is None or viewport is None:
            return
        panel._runtime.pending_auto_scroll = None
        if pending == "strict" or panel._runtime.smart_auto_scroll_active:
            viewport.scroll_to_bottom()

    @staticmethod
    def _render_terminal_too_small(width: int | None = None) -> list[str]:
        line = "Terminal window is too small."
        return [line if width is None else clip_display(line, 0, max(0, width))]

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

    def _restore_cursor(self, frame: RenderResult | list[str]) -> None:
        if (
            self._menu._input is None
            or self._menu._alert is not None
            or not self._menu._menu_box_visible
        ):
            stdout.write("\033[?25l")
            return
        # Preserve the tested list-returning composition helpers. The real render
        # path passes its result directly, so cursor ownership stays explicit.
        result = frame if isinstance(frame, RenderResult) else self._last_composition
        if result is None or result.cursor is None:
            stdout.write("\033[?25l")
            return
        row, column = result.cursor
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
            panel._runtime.pending_auto_scroll = None
            return
        if mode == "smart" and not panel._runtime.smart_auto_scroll_active:
            return
        panel._runtime.pending_auto_scroll = mode
        if panel._runtime.viewport is not None:
            panel._runtime.viewport.scroll_to_bottom()

    def scroll_panel(self, panel: ContentPanel, direction: ScrollDirection) -> None:
        """Scroll one panel and update its smart-follow state."""
        viewport = panel._runtime.viewport
        if viewport is None:
            return
        previous_y = viewport.offset_y
        getattr(viewport, f"scroll_{direction}")()
        if direction == "up" and viewport.offset_y < previous_y:
            panel._runtime.smart_auto_scroll_active = False
        elif direction == "down" and viewport.is_at_bottom():
            panel._runtime.smart_auto_scroll_active = True
