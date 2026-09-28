from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING

from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.render.terminal_renderer import AutoScrollMode
from tuiloom.screen_content import ContentSize, ScreenContent

if TYPE_CHECKING:
    from tuiloom.event_loop.source_worker import SourceWorker
    from tuiloom.render.viewport import Viewport
    from tuiloom.terminal_menu import TerminalMenu


class ContentPanel:
    """Stable handle for one independently rendered menu content source."""

    __slots__ = (
        "_menu",
        "_content",
        "_description",
        "_auto_scroll",
        "_weight",
        "_min_height",
        "_max_height",
        "_renderer",
        "_viewport",
        "_worker",
        "_generation",
        "_pending_content",
        "_dynamic_in_flight",
        "_next_dynamic_at",
        "_effective_size",
        "_responsive_request_id",
        "_responsive_refresh_pending",
        "_removed",
        "_retiring",
        "_smart_auto_scroll_active",
        "_pending_auto_scroll",
        "_remove_when_finished",
    )

    def __init__(
        self,
        menu: TerminalMenu,
        content: ScreenContent,
        description: str,
        auto_scroll: AutoScrollMode | None,
        *,
        weight: float = 1,
        min_height: int = 1,
        max_height: int | None = None,
    ) -> None:
        self._menu = menu
        if not isinstance(content, ScreenContent):
            raise TypeError("ContentPanel content must be a ScreenContent")
        self._validate_layout(weight, min_height, max_height)
        self._content = content
        self._description = description
        self._auto_scroll = auto_scroll
        self._weight = weight
        self._min_height = min_height
        self._max_height = max_height
        self._renderer = ContentRenderer(content)
        self._viewport: Viewport | None = None
        self._worker: SourceWorker | None = None
        self._generation = 0
        self._pending_content: ScreenContent | None = None
        self._dynamic_in_flight = False
        self._next_dynamic_at = 0.0
        self._effective_size: ContentSize | None = None
        self._responsive_request_id = 0
        self._responsive_refresh_pending = content._kind == "responsive"
        self._removed = False
        self._retiring = False
        self._smart_auto_scroll_active = True
        self._pending_auto_scroll: AutoScrollMode | None = None
        self._remove_when_finished = False

    @property
    def description(self) -> str:
        """Return the label displayed on this panel."""
        return self._description

    @property
    def position(self) -> int:
        """Return this panel's zero-based position in its owning menu."""
        return self._menu._position_of_content_panel(self)

    @property
    def auto_scroll(self) -> AutoScrollMode | None:
        """Return this panel's iterator auto-scroll policy."""
        return self._auto_scroll

    @property
    def content(self) -> ScreenContent:
        """Return the configuration currently mounted by this panel."""
        return self._content

    @property
    def weight(self) -> float:
        """Return the relative share of visible panel height, including borders."""
        return self._weight

    @property
    def min_height(self) -> int:
        """Return the minimum number of visible content rows, excluding borders."""
        return self._min_height

    @property
    def max_height(self) -> int | None:
        """Return the visible content row limit, or None for an unlimited panel."""
        return self._max_height

    def set_layout(
        self,
        *,
        weight: float = 1,
        min_height: int = 1,
        max_height: int | None = None,
    ) -> None:
        """Replace all sizing options; omitted options return to their defaults."""
        self._menu._set_content_panel_layout(self, weight, min_height, max_height)

    @staticmethod
    def _validate_layout(
        weight: float, min_height: int, max_height: int | None
    ) -> None:
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise TypeError("weight must be a finite positive number")
        if weight <= 0 or (isinstance(weight, float) and not isfinite(weight)):
            raise ValueError("weight must be a finite positive number")
        if min_height is None:
            raise TypeError("min_height must be a positive integer")
        ScreenContent._validate_minimum("min_height", min_height)
        ScreenContent._validate_minimum("max_height", max_height)
        if max_height is not None and max_height < min_height:
            raise ValueError("max_height must be greater than or equal to min_height")

    def set_content(self, content: ScreenContent) -> None:
        """Replace this panel's content without changing its identity."""
        self._menu._set_content_panel_content(self, content)

    def refresh(self) -> None:
        """Request a fresh responsive rendering for the current size."""
        self._menu._refresh_content_panel(self)

    def set_description(self, description: str) -> None:
        """Replace this panel's visible and shutdown description."""
        self._menu._set_content_panel_description(self, description)

    def set_auto_scroll(self, mode: AutoScrollMode | None) -> None:
        """Set this panel's iterator auto-scroll policy."""
        self._menu._set_content_panel_auto_scroll(self, mode)

    def move(self, position: int) -> None:
        """Move this panel to a zero-based position in its owning menu."""
        self._menu._move_content_panel(self, position)

    def remove(self) -> None:
        """Remove this panel and cooperatively retire its worker."""
        self._menu._remove_content_panel(self)
