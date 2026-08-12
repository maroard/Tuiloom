from dataclasses import dataclass
from itertools import zip_longest

from tuiloom.render.terminal_text import (
    RESET_SGR,
    clip_display,
    display_width,
    normalize_line,
    visual_cells,
)


@dataclass(frozen=True)
class SegmentChange:
    """Describe one changed run of terminal cells."""

    row: int
    column: int
    content: str
    clear_width: int = 0


def _changed_spans(
    previous_line: str,
    current_line: str,
) -> list[tuple[int, int]]:
    """Return zero-based half-open spans of unequal visual cells."""
    previous_cells = visual_cells(previous_line)
    current_cells = visual_cells(current_line)
    changed_columns = [
        column
        for column, (previous, current) in enumerate(
            zip_longest(previous_cells, current_cells)
        )
        if previous != current
    ]

    if not changed_columns:
        return []

    spans: list[tuple[int, int]] = []
    start = previous = changed_columns[0]

    for column in changed_columns[1:]:
        if column != previous + 1:
            spans.append((start, previous + 1))
            start = column
        previous = column

    spans.append((start, previous + 1))
    return spans


def get_segment_changes(
    previous_lines: list[str],
    current_lines: list[str],
) -> list[SegmentChange]:
    """Return changed visual segments between complete terminal frames."""
    changes: list[SegmentChange] = []

    for row in range(max(len(previous_lines), len(current_lines))):
        previous_exists = row < len(previous_lines)
        current_exists = row < len(current_lines)
        previous_raw = previous_lines[row] if previous_exists else ""
        current_raw = current_lines[row] if current_exists else ""

        if previous_exists == current_exists and previous_raw == current_raw:
            continue

        previous_line = normalize_line(previous_raw)
        current_line = normalize_line(current_raw)

        if previous_line == current_line:
            if previous_exists != current_exists:
                changes.append(
                    SegmentChange(
                        row=row + 1,
                        column=1,
                        content=RESET_SGR + RESET_SGR,
                    )
                )
            continue

        for start, end in _changed_spans(previous_line, current_line):
            clipped = clip_display(current_line, start, end)
            visible_width = display_width(clipped)
            changes.append(
                SegmentChange(
                    row=row + 1,
                    column=start + 1,
                    content=RESET_SGR + clipped + RESET_SGR,
                    clear_width=max(0, end - start - visible_width),
                )
            )

    return changes
