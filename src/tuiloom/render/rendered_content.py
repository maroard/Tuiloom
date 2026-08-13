from dataclasses import dataclass


@dataclass
class RenderedContent:
    """Store normalized content lines, dimensions, and completion state."""

    lines: list[str]
    width: int
    height: int
    finished: bool
    revision: int = 0
