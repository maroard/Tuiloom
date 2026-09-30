"""Validate vertical spans in a menu's public row matrix."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuiloom.content_panel import ContentPanel


@dataclass(frozen=True, slots=True)
class VerticalSpan:
    """One panel occupying the same column in consecutive layout rows."""

    panel: ContentPanel
    start: int
    stop: int
    column: int


def find_vertical_spans(
    rows: tuple[tuple[ContentPanel, ...], ...],
) -> tuple[VerticalSpan, ...]:
    """Reject malformed repetitions and return disjoint spanning row ranges."""
    occurrences: dict[ContentPanel, list[tuple[int, int]]] = defaultdict(list)
    for row_index, row in enumerate(rows):
        if len(set(row)) != len(row):
            raise ValueError("content layout repeats a panel within one row")
        for column, panel in enumerate(row):
            occurrences[panel].append((row_index, column))

    spans: list[VerticalSpan] = []
    occupied_rows: set[int] = set()
    for panel, positions in occurrences.items():
        if len(positions) == 1:
            continue
        first, column = positions[0]
        stop = positions[-1][0] + 1
        if positions != [(index, column) for index in range(first, stop)]:
            raise ValueError("a vertical span must stay in one adjacent column")
        width = len(rows[first])
        if width < 2 or any(len(rows[index]) != width for index in range(first, stop)):
            raise ValueError("vertical span rows need matching column counts")
        row_range = set(range(first, stop))
        if occupied_rows & row_range:
            raise ValueError("vertical spans cannot overlap")
        occupied_rows.update(row_range)
        spans.append(VerticalSpan(panel, first, stop, column))
    return tuple(sorted(spans, key=lambda span: span.start))


def dissolve_invalid_spans(
    rows: tuple[tuple[ContentPanel, ...], ...],
) -> tuple[tuple[ContentPanel, ...], ...]:
    """Keep unaffected spans when a removed panel breaks one block's geometry."""
    occurrences: dict[ContentPanel, list[tuple[int, int]]] = defaultdict(list)
    for row_index, row in enumerate(rows):
        for column, panel in enumerate(row):
            occurrences[panel].append((row_index, column))
    invalid: set[ContentPanel] = set()
    for panel, positions in occurrences.items():
        if len(positions) < 2:
            continue
        first, column = positions[0]
        stop = positions[-1][0] + 1
        if (
            positions != [(index, column) for index in range(first, stop)]
            or len(rows[first]) < 2
            or any(len(rows[index]) != len(rows[first]) for index in range(first, stop))
        ):
            invalid.add(panel)
    seen: set[ContentPanel] = set()
    repaired: list[tuple[ContentPanel, ...]] = []
    for row in rows:
        kept = tuple(
            panel for panel in row if panel not in invalid or panel not in seen
        )
        seen.update(panel for panel in kept if panel in invalid)
        if kept:
            if any(panel in invalid for panel in kept):
                repaired.extend((panel,) for panel in kept)
            else:
                repaired.append(kept)
    return tuple(repaired)


def validate_spanned_bounds(
    rows: tuple[tuple[ContentPanel, ...], ...], spans: tuple[VerticalSpan, ...]
) -> None:
    """Check static bounds and collapse rules for each spanning block."""
    for span in spans:
        for row in rows[span.start : span.stop]:
            if any(panel.collapsed for panel in row):
                raise ValueError("a vertical span cannot contain collapsed panels")
        minimum, maximum, _ = span_block_sizing(rows, span)
        if maximum is not None and minimum > maximum:
            raise ValueError("vertical span height bounds do not intersect")


def span_block_sizing(
    rows: tuple[tuple[ContentPanel, ...], ...], span: VerticalSpan
) -> tuple[int, int | None, float]:
    """Return minimum/maximum complete frame heights and track weight."""
    row_minimums: list[int] = []
    row_maximums: list[int | None] = []
    weight = 0.0
    for row in rows[span.start : span.stop]:
        others = [panel for panel in row if panel is not span.panel]
        minimum = max(panel.min_height for panel in others) + 2
        maximum = min(
            (panel.max_height + 2 for panel in others if panel.max_height is not None),
            default=None,
        )
        if maximum is not None and maximum < minimum:
            raise ValueError("content row height bounds do not intersect")
        row_minimums.append(minimum)
        row_maximums.append(maximum)
        weight += sum(panel.height_weight for panel in others) / len(others)
    minimum = max(span.panel.min_height + 2, sum(row_minimums))
    maximums = [
        span.panel.max_height + 2 if span.panel.max_height is not None else None,
        sum(value for value in row_maximums if value is not None)
        if all(value is not None for value in row_maximums)
        else None,
    ]
    limits = [value for value in maximums if value is not None]
    return minimum, min(limits) if limits else None, weight * span.panel.height_weight
