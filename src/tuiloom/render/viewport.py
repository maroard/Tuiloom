from tuiloom.render.rendered_content import RenderedContent
from tuiloom.render.terminal_text import clip_display, ljust_display


class Viewport:
    """Clip rendered content using bounded horizontal and vertical offsets."""

    def __init__(
        self, rendered_content: RenderedContent, width: int, height: int
    ) -> None:
        """Create a positive-sized viewport over normalized content."""
        self.content = rendered_content

        if type(width) is not int or type(height) is not int:
            raise TypeError(
                "Viewport width and height must be int, "
                f"got width: {type(width).__name__}, "
                f"height: {type(height).__name__}"
            )

        if width <= 0 or height <= 0:
            raise ValueError(
                "Viewport width and height must be positive integers, "
                f"got width={width}, height={height}"
            )

        self.width = width
        self.height = height
        self.offset_x = 0
        self.offset_y = 0

    def render(self) -> str:
        """Render the visible content region at the current offsets."""
        max_offset_x = max(0, self.content.width - self.width)
        max_offset_y = max(0, self.content.height - self.height)

        self.offset_x = min(self.offset_x, max_offset_x)
        self.offset_y = min(self.offset_y, max_offset_y)

        visible_lines = self.content.lines[self.offset_y : self.offset_y + self.height]

        rendered_lines = []

        for line in visible_lines:
            visible_part = clip_display(
                line,
                self.offset_x,
                self.offset_x + self.width,
            )
            rendered_lines.append(ljust_display(visible_part, self.width))

        while len(rendered_lines) < self.height:
            rendered_lines.append(" " * self.width)

        return "\n".join(rendered_lines)

    def scroll_up(self) -> None:
        """Move the vertical offset one row toward the top boundary."""
        if self.offset_y > 0:
            self.offset_y -= 1

    def scroll_down(self) -> None:
        """Move the vertical offset one row toward the bottom boundary."""
        max_offset_y = max(0, self.content.height - self.height)

        if self.offset_y < max_offset_y:
            self.offset_y += 1

    def scroll_left(self) -> None:
        """Move the horizontal offset one column toward the left boundary."""
        if self.offset_x > 0:
            self.offset_x -= 1

    def scroll_right(self) -> None:
        """Move the horizontal offset one column toward the right boundary."""
        max_offset_x = max(0, self.content.width - self.width)

        if self.offset_x < max_offset_x:
            self.offset_x += 1
