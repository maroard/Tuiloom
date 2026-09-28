"""Allocate complete panel frames without changing panel or viewport state."""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tuiloom.content_panel import ContentPanel


def allocate_panel_heights(
    panels: tuple[ContentPanel, ...], available: int
) -> list[int] | None:
    """Share rows including borders by weight, returning inner viewport heights.

    Height bounds count content rows, so each gains two border rows during
    allocation. Weights apply to the full frame; borders are removed afterward.
    Return None when minimums do not fit. Integer rounding uses the largest
    fractional remainders, with ties resolved in panel display order.
    Collapsed panels use a fixed inner height instead of their expanded bounds.
    """
    heights = [
        (panel.collapsed_height if panel.collapsed else panel.min_height) + 2
        for panel in panels
    ]
    if sum(heights) > available:
        return None

    weights = [Fraction(panel.weight) for panel in panels]
    minimums = [Fraction(height) for height in heights]
    maximums = [
        Fraction(panel.collapsed_height + 2)
        if panel.collapsed
        else Fraction(
            panel.max_height + 2 if panel.max_height is not None else available
        )
        for panel in panels
    ]
    remaining = available
    active = list(range(len(panels)))
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
