from dataclasses import dataclass


@dataclass(frozen=True)
class RenderResult:
    """Carry physical lines and an optional one-based input cursor together."""

    lines: list[str]
    cursor: tuple[int, int] | None = None
    too_small: bool = False


@dataclass
class RenderedContent:
    """Store normalized content lines, dimensions, and completion state."""

    lines: list[str]
    width: int
    height: int
    finished: bool
    revision: int = 0
