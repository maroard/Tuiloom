"""Allocate complete panel frames without changing panel or viewport state."""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuiloom.content_panel import ContentPanel


def allocate_panel_heights(
    rows: tuple[tuple[ContentPanel, ...], ...], available: int
) -> list[int] | None:
    """Share rows including borders by mean height weight and shared bounds.

    Height bounds count content rows, so each gains two border rows during
    allocation. Weights apply to the full frame; borders are removed afterward.
    Return None when minimums do not fit. Integer rounding uses the largest
    fractional remainders, with ties resolved in row display order.
    Collapsed rows use their common fixed inner height instead of expanded bounds.
    """
    heights = [
        (
            row[0].collapsed_height
            if row[0].collapsed
            else max(panel.min_height for panel in row)
        )
        + 2
        for row in rows
    ]
    if sum(heights) > available:
        return None

    weights = [
        sum((Fraction(panel.height_weight) for panel in row), Fraction(0)) / len(row)
        for row in rows
    ]
    minimums = [Fraction(height) for height in heights]
    maximums = [
        Fraction(row[0].collapsed_height + 2)
        if row[0].collapsed
        else Fraction(
            min(
                (panel.max_height + 2 for panel in row if panel.max_height is not None),
                default=available,
            )
        )
        for row in rows
    ]
    remaining = available
    active = list(range(len(rows)))
    while remaining and active:
        total_weight = sum(weights[index] for index in active)
        shares = {index: remaining * weights[index] / total_weight for index in active}
        bounded = {
            index: min(
                max(shares[index], minimums[index]),
                maximums[index],
            )
            for index in active
        }
        bounded_total = sum(bounded.values())
        if bounded_total != remaining:
            # Fix only the bounds in the direction of the required adjustment.
            # Fixing both at once can consume too many rows even for a valid layout.
            constrained = [
                index
                for index in active
                if (
                    shares[index] < bounded[index]
                    if bounded_total > remaining
                    else shares[index] > bounded[index]
                )
            ]
            for index in constrained:
                heights[index] = int(bounded[index])
                remaining -= heights[index]
            active = [index for index in active if index not in constrained]
            continue

        for index in active:
            heights[index] = int(bounded[index])
            remaining -= heights[index]
        by_remainder = sorted(
            active, key=lambda index: bounded[index] % 1, reverse=True
        )
        for index in by_remainder[:remaining]:
            heights[index] += 1
        break
    return [height - 2 for height in heights]


def allocate_panel_widths(
    row: tuple[ContentPanel, ...], available: int
) -> list[int] | None:
    """Share complete frame widths by panel width weight, keeping one inner column."""
    if available < 3 * len(row):
        return None
    weights = [Fraction(panel.width_weight) for panel in row]
    frames = [0] * len(row)
    remaining = available
    active = list(range(len(row)))
    while active:
        total_weight = sum(weights[index] for index in active)
        shares = {
            index: Fraction(remaining) * weights[index] / total_weight
            for index in active
        }
        constrained = [index for index in active if shares[index] < 3]
        if not constrained:
            for index in active:
                frames[index] = int(shares[index])
            leftover = remaining - sum(frames[index] for index in active)
            by_remainder = sorted(
                active, key=lambda index: shares[index] % 1, reverse=True
            )
            for index in by_remainder[:leftover]:
                frames[index] += 1
            break
        for index in constrained:
            frames[index] = 3
            remaining -= 3
        active = [index for index in active if index not in constrained]
    return [frame - 2 for frame in frames]
