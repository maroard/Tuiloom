"""Define the accepted string values for display and refresh configuration.

These are typing aliases, not enums to construct. Pass their literal strings
to the corresponding menu, panel or content factory parameters.

Attributes:
    AutoScrollMode: ``"smart"`` follows new stream output until manual scrolling
        moves away from the bottom, resuming when the bottom is reached again.
        ``"strict"`` follows every new stream batch despite manual scrolling.
        Panel parameters also accept ``None`` to disable automatic following.
    MenuPresentation: ``"inline"`` reserves command rows below content panels;
        ``"overlay"`` draws the command box over their full-height layout. A
        menu constructor also accepts ``None`` to inherit on opening.
    ContentRefreshMode: ``"resize"`` evaluates responsive content on its initial
        layout and size changes, or explicit refresh requests. ``"continuous"``
        also schedules periodic reevaluations while size stays the same, at the
        application's nominal 60 Hz cadence. Explicit refresh and layout changes
        can request additional evaluations; requests coalesce and calls never
        overlap within a panel. Waiting to quit suspends new evaluations for
        either mode while existing work drains.
    SelectionStyle: ``"marker"`` shows a leading marker; ``"reverse"`` uses
        SGR 7 across the full selected row. Menus and panels configure it
        independently.
"""

from typing import Literal

type AutoScrollMode = Literal["smart", "strict"]
"""Follow streamed output until manual scroll (smart), or on every batch (strict)."""
type MenuPresentation = Literal["inline", "overlay"]
"""Place commands below panels (inline), or draw them over the panels (overlay)."""
type ContentRefreshMode = Literal["resize", "continuous"]
"""Evaluate responsive content on size/refresh changes, or continuously as well."""
type SelectionStyle = Literal["marker", "reverse"]
"""Select an item with a text marker or terminal SGR reverse video."""
