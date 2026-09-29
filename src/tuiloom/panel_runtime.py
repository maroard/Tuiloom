"""Runtime state and transitions for one stable public content-panel handle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tuiloom.configuration import AutoScrollMode
from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.screen_content import ContentSize, ScreenContent

if TYPE_CHECKING:
    from tuiloom.event_loop.source_worker import SourceWorker
    from tuiloom.render.viewport import Viewport


@dataclass(slots=True)
class PanelRuntime:
    """Group worker, rendering and viewport state independently of configuration.

    A replacement advances generation immediately to ignore stale events, but
    leaves activity true until the old worker returns. Generations distinguish
    sources; responsive request IDs distinguish size requests within a source.
    """

    renderer: ContentRenderer
    viewport: Viewport | None = None
    worker: SourceWorker | None = None
    generation: int = 0
    pending_content: ScreenContent | None = None
    dynamic_in_flight: bool = False
    next_dynamic_at: float = 0.0
    last_animation_index: int | None = None
    effective_size: ContentSize | None = None
    responsive_request_id: int = 0
    responsive_refresh_pending: bool = False
    retiring: bool = False
    smart_auto_scroll_active: bool = True
    pending_auto_scroll: AutoScrollMode | None = None
    remove_when_finished: bool = False

    @property
    def blocks_exit(self) -> bool:
        """Report live work, including a canceled source still finishing."""
        return (
            self.worker is not None
            and self.worker.is_alive()
            and (
                self.renderer.state == "streaming"
                or self.dynamic_in_flight
                or self.pending_content is not None
                or self.retiring
            )
        )

    def request_replacement(self, content: ScreenContent) -> None:
        """Keep only the latest requested source and invalidate older events."""
        self.pending_content = content
        self.generation += 1

    def begin_retirement(self) -> None:
        """Retire the current source without starting a queued replacement."""
        self.retiring = True
        self.pending_content = None

    def mount(self, content: ScreenContent) -> None:
        """Reset presentation state after the previous worker has terminated."""
        self.pending_content = None
        self.renderer = ContentRenderer(content)
        self.viewport = None
        self.effective_size = None
        self.responsive_refresh_pending = content._kind in ("responsive", "animated")
        self.last_animation_index = None
        self.smart_auto_scroll_active = True
        self.pending_auto_scroll = None
