from shutil import get_terminal_size
from sys import stdout

from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.render.menu_renderer import MenuRenderer
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

    def render(self) -> None:
        """Render and write one complete terminal frame."""
        rendered_content = self.content_renderer.update()
        menu_render = self.menu_renderer.render()

        terminal_size = get_terminal_size()
        terminal_width = terminal_size.columns
        terminal_height = terminal_size.lines

        menu_lines = menu_render.splitlines() or [""]
        menu_height = len(menu_lines)
        menu_width = max(len(line) for line in menu_lines)

        viewport_width = terminal_width
        viewport_height = terminal_height - menu_height - self.spacing

        if viewport_width <= 0 or viewport_height <= 0 or menu_width > terminal_width:
            self._render_terminal_too_small()
            return

        if self.viewport is None:
            self.viewport = Viewport(rendered_content, viewport_width, viewport_height)
        else:
            self.viewport.content = rendered_content
            self.viewport.width = viewport_width
            self.viewport.height = viewport_height

        viewport_render = self.viewport.render()

        render = viewport_render + "\n" * self.spacing + menu_render

        screen = "\033[H\033[J" + render + "\033[J"

        stdout.write(screen)
        stdout.flush()

    def _render_terminal_too_small(self) -> None:
        """Replace the frame with a terminal-size warning."""
        screen = "\033[H\033[JTerminal window is too small.\033[J"

        stdout.write(screen)
        stdout.flush()

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
