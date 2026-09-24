"""Shared horizontal choice geometry for rendering and navigation."""

from __future__ import annotations

from dataclasses import dataclass

from tuiloom.command import MenuChoice
from tuiloom.render.terminal_text import display_width


@dataclass(frozen=True, slots=True)
class ChoiceLine:
    indices: tuple[int, ...]
    starts: tuple[int, ...]


def choice_indent(width: int) -> int:
    """Indent option lines by two cells whenever the width permits."""
    return min(2, max(0, width - 1))


def choice_token(label: str, *, selected: bool, cursor: bool) -> str:
    """Render one option without reserving space for an absent checkmark."""
    return f"{'>' if cursor else ' '} " + ("✓ " if selected else "") + label


def choice_slot_width(label: str) -> int:
    """Reserve checkmark space after the label when it is absent."""
    return 4 + display_width(label)


def choice_lines(choice: MenuChoice, width: int) -> tuple[ChoiceLine, ...]:
    """Group options by declared row, then wrap only between options."""
    result: list[ChoiceLine] = []
    width = max(1, width)
    indent = choice_indent(width)
    for declared in range(choice.rows):
        indices: list[int] = []
        starts: list[int] = []
        used = indent
        for index, option in enumerate(choice.options):
            if option.row != declared:
                continue
            size = choice_slot_width(option.label)
            separator = 2 if indices else 0
            if indices and used + separator + size > width:
                result.append(ChoiceLine(tuple(indices), tuple(starts)))
                indices, starts, used = [], [], indent
                separator = 0
            start = used + separator
            indices.append(index)
            starts.append(start)
            used = start + size
        if indices:
            result.append(ChoiceLine(tuple(indices), tuple(starts)))
    return tuple(result)
