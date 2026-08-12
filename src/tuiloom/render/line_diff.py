from dataclasses import dataclass
from itertools import zip_longest


@dataclass(frozen=True)
class LineChange:
    """Describe one complete terminal line replacement."""

    row: int
    content: str


def get_line_changes(
    previous_lines: list[str],
    current_lines: list[str],
) -> list[LineChange]:
    """Return the complete lines that differ between two terminal frames."""
    changes: list[LineChange] = []
    missing = object()

    for row, (previous_line, current_line) in enumerate(
        zip_longest(previous_lines, current_lines, fillvalue=missing),
        start=1,
    ):
        if previous_line != current_line:
            content = "" if current_line is missing else current_line
            assert isinstance(content, str)
            changes.append(LineChange(row=row, content=content))

    return changes
