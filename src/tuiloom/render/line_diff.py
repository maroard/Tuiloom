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

    for row, (previous_line, current_line) in enumerate(
        zip_longest(previous_lines, current_lines, fillvalue=""),
        start=1,
    ):
        if previous_line != current_line:
            changes.append(LineChange(row=row, content=current_line))

    return changes
