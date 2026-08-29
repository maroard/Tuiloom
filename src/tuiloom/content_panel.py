from __future__ import annotations

from typing import TYPE_CHECKING

from tuiloom.render.content_renderer import ContentRenderer, ContentSource
from tuiloom.render.terminal_renderer import AutoScrollMode

if TYPE_CHECKING:
    from tuiloom.event_loop.source_worker import SourceWorker
    from tuiloom.render.viewport import Viewport
    from tuiloom.terminal_menu import TerminalMenu


class ContentPanel:
    """Stable handle for one independently rendered menu content source."""

    __slots__ = (
        "_menu",
        "_source",
        "_description",
        "_auto_scroll",
        "_renderer",
        "_viewport",
        "_worker",
        "_generation",
        "_pending_source",
        "_dynamic_in_flight",
        "_next_dynamic_at",
        "_removed",
        "_retiring",
        "_smart_auto_scroll_active",
        "_pending_auto_scroll",
        "_remove_when_finished",
    )

    def __init__(
        self,
        menu: TerminalMenu,
        source: ContentSource,
        description: str,
        auto_scroll: AutoScrollMode | None,
    ) -> None:
        self._menu = menu
        self._source = source
        self._description = description
        self._auto_scroll = auto_scroll
        self._renderer = ContentRenderer(source)
        self._viewport: Viewport | None = None
        self._worker: SourceWorker | None = None
        self._generation = 0
        self._pending_source: ContentSource | None = None
        self._dynamic_in_flight = False
        self._next_dynamic_at = 0.0
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
