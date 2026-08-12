from os import terminal_size
from shutil import get_terminal_size
from sys import stdout

from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.segment_diff import SegmentChange, get_segment_changes
from tuiloom.render.terminal_text import display_width, normalize_line
from tuiloom.render.viewport import Viewport


class TerminalRenderer:
    """Compose and write the content viewport and menu to the terminal."""

    def __init__(
        self,
        menu_renderer: MenuRenderer,
        content_renderer: ContentRenderer,
        spacing: int,
    ) -> None:
        """Store the renderers and spacing used to compose each frame."""
        self.menu_renderer = menu_renderer
        self.content_renderer = content_renderer
        self.spacing = spacing
        self.viewport: Viewport | None = None
        self._previous_lines: list[str] | None = None
        self._previous_terminal_size: terminal_size | None = None

    def render(self, input_buffer: str = "") -> None:
        """Render and write one complete terminal frame."""
        current_terminal_size = get_terminal_size()
        lines = self._compose_frame(
            input_buffer,
            current_terminal_size.columns,
            current_terminal_size.lines,
        )

        if (
            self._previous_lines is None
            or self._previous_terminal_size != current_terminal_size
        ):
            self._write_full_frame(lines)

        else:
            changes = get_segment_changes(self._previous_lines, lines)

            if not changes:
                return

            self._write_segment_changes(changes)

        self._restore_input_cursor(lines)

        stdout.flush()

        self._previous_lines = lines
        self._previous_terminal_size = current_terminal_size

    def _compose_frame(
        self,
        input_buffer: str,
        terminal_width: int,
        terminal_height: int,
    ) -> list[str]:
        """Compose the logical terminal frame for the current state."""
        rendered_content = self.content_renderer.update()
        menu_render = self.menu_renderer.render() + input_buffer

        menu_lines = menu_render.splitlines() or [""]
        menu_height = len(menu_lines)
        menu_width = max(display_width(line) for line in menu_lines)

        viewport_width = terminal_width
        viewport_height = terminal_height - menu_height - self.spacing

        if viewport_width <= 0 or viewport_height <= 0 or menu_width > terminal_width:
            return self._render_terminal_too_small()

        if self.viewport is None:
            self.viewport = Viewport(rendered_content, viewport_width, viewport_height)
        else:
            self.viewport.content = rendered_content
            self.viewport.width = viewport_width
            self.viewport.height = viewport_height

        viewport_render = self.viewport.render()

        render = viewport_render + "\n" * self.spacing + menu_render

        return [normalize_line(line) for line in render.split("\n")]

    def _render_terminal_too_small(self) -> list[str]:
        """Return the frame displayed when the terminal is too small."""
        return ["Terminal window is too small."]

    def _write_full_frame(self, lines: list[str]) -> None:
        """Replace the complete terminal frame."""
        safe_lines = [normalize_line(line) for line in lines]
        stdout.write("\033[?25l\033[H\033[J" + "\n".join(safe_lines))

    def _write_segment_changes(self, changes: list[SegmentChange]) -> None:
        """Write changed terminal-cell segments at precise coordinates."""
        stdout.write("\033[?25l")

        for change in changes:
            safe_content = normalize_line(change.content)
            stdout.write(f"\033[{change.row};{change.column}H{safe_content}")

            if change.clear_width:
                stdout.write(f"\033[{change.clear_width}X")

    def _get_cursor_position(self, lines: list[str]) -> tuple[int, int]:
        """Return the terminal position immediately after the input line."""
        return len(lines), display_width(lines[-1]) + 1

    def _restore_input_cursor(self, lines: list[str]) -> None:
        """Show the cursor immediately after the current input."""
        row, column = self._get_cursor_position(lines)
        stdout.write(f"\033[{row};{column}H\033[?25h")

    def invalidate(self) -> None:
        """Force a complete redraw of the next terminal frame."""
        self._previous_lines = None
        self._previous_terminal_size = None

    def set_content_renderer(self, content_renderer: ContentRenderer) -> None:
        """Replace active content and reset source-specific rendering state."""
        self.content_renderer = content_renderer
        self.viewport = None
        self.invalidate()

    def scroll_up(self) -> None:
        """Move the viewport one row upward when it exists."""
        if self.viewport is not None:
            self.viewport.scroll_up()

    def scroll_down(self) -> None:
        """Move the viewport one row downward when it exists."""
        if self.viewport is not None:
            self.viewport.scroll_down()

    def scroll_left(self) -> None:
        """Move the viewport one column left when it exists."""
        if self.viewport is not None:
            self.viewport.scroll_left()

    def scroll_right(self) -> None:
        """Move the viewport one column right when it exists."""
        if self.viewport is not None:
            self.viewport.scroll_right()
