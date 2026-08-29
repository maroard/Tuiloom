from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Queue
from selectors import EVENT_READ, BaseSelector, DefaultSelector
from shutil import get_terminal_size
from socket import socketpair
from time import monotonic
from typing import TYPE_CHECKING

from tuiloom.background_work import BackgroundWork
from tuiloom.content_panel import ContentPanel
from tuiloom.event_loop.source_event import SourceEvent
from tuiloom.event_loop.source_worker import SourceWorker
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.render.content_renderer import ContentRenderer, ContentSource
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer

if TYPE_CHECKING:
    from tuiloom.terminal_menu import TerminalMenu


class EventLoop:
    """Coordinate input, content sources, and frame scheduling for one menu."""

    _FRAME_INTERVAL = 1 / 60
    _STATE_CHECK_INTERVAL = 0.1
    _SOURCE_QUEUE_SIZE = 256

    def __init__(
        self,
        menu: TerminalMenu,
        input_handler: InputHandler,
        menu_renderer: MenuRenderer,
        terminal_renderer: TerminalRenderer,
        content_renderer: ContentRenderer,
        *,
        clock: Callable[[], float] = monotonic,
        selector_factory: Callable[[], BaseSelector] = DefaultSelector,
    ) -> None:
        """Create an event loop over initialized menu renderers."""
        self._menu = menu
        self._input_handler = input_handler
        self._menu_renderer = menu_renderer
        self._terminal_renderer = terminal_renderer
        self._content_renderer = content_renderer
        self._clock = clock
        self._selector = selector_factory()
        self._wakeup_reader, self._wakeup_writer = socketpair()
        self._wakeup_reader.setblocking(False)
        self._wakeup_writer.setblocking(False)
        self._selector.register(input_handler.fileno(), EVENT_READ, "input")
        self._selector.register(self._wakeup_reader, EVENT_READ, "source")

        self._source_events: Queue[SourceEvent] = Queue(maxsize=self._SOURCE_QUEUE_SIZE)
        self._generation = 0
        self._source_worker: SourceWorker | None = None
        self._pending_source: tuple[ContentSource, str] | None = None
        self._retiring_panels: list[ContentPanel] = []
        self._dirty = True
        now = self._clock()
        self._next_frame_at = now
        self._next_state_check_at = now
        self._dynamic_in_flight = False
        self._next_dynamic_at = now
        self._terminal_size = get_terminal_size()
        self._closed = False

        primary = menu._primary_content_panel
        if primary is not None:
            primary._renderer = content_renderer
        for panel in menu.content_panels:
            self._install_panel_worker(panel)
        self._sync_primary_aliases()

    def run(self) -> None:
        """Process events until the owning menu stops."""
        while self._menu._running:
            self.run_once()

    def run_once(self) -> None:
        """Process one selectable event-loop turn."""
        self._progress_panel_transitions()
        ready = self._selector.select(self._get_wait_timeout())

        for key, _ in ready:
            if key.data == "source":
                self._drain_wakeup()
                self._drain_source_events()

        self._drain_input()
        self._request_dynamic_updates()
        completed_menu = self._menu.app._dispatch_output_task_outcome()

        if completed_menu is self._menu:
            self.request_render(immediate=True)

        self._check_visible_state()
        self._render_if_due()

    def request_render(self, immediate: bool = False) -> None:
        """Mark visible state dirty for the next permitted frame."""
        self._dirty = True

        if immediate:
            self._next_frame_at = self._clock()

    @property
    def active_work(self) -> BackgroundWork | None:
        """Return source work that currently prevents a safe menu exit."""
        active = self.active_panels
        return active[0]._worker if active else None

    @property
    def active_panels(self) -> tuple[ContentPanel, ...]:
        """Return logical panels whose work currently blocks safe exit."""
        active: list[ContentPanel] = []
        for panel in (*self._menu.content_panels, *self._retiring_panels):
            worker = panel._worker
            if worker is None or not worker.is_alive():
                continue
            if panel._renderer.state == "streaming" or panel._dynamic_in_flight:
                active.append(panel)
        return tuple(dict.fromkeys(active))

    @property
    def retiring_panels(self) -> tuple[ContentPanel, ...]:
        """Return removed panels whose workers have not terminated yet."""
        return tuple(self._retiring_panels)

    def add_content_panel(self, panel: ContentPanel) -> None:
        """Start runtime work for a panel added while the loop is active."""
        self._install_panel_worker(panel)
        self._sync_primary_aliases()
        self.request_render(immediate=True)

    def replace_content_panel(
        self,
        panel: ContentPanel,
        source: ContentSource,
    ) -> None:
        """Replace one panel only after its previous worker terminates."""
        panel._pending_source = source
        self._generation += 1
        panel._generation = self._generation
        panel._dynamic_in_flight = False
        worker = panel._worker
        if worker is not None and worker.is_alive():
            worker.cancel()
            self._notify_source()
        else:
            if worker is not None:
                worker.join()
            self._apply_panel_source(panel, source)
        self._sync_primary_aliases()
        self.request_render(immediate=True)

    def retire_content_panel(self, panel: ContentPanel) -> None:
        """Cancel and track a removed panel until its worker stops."""
        panel._retiring = True
        panel._pending_source = None
        worker = panel._worker
        if worker is not None and worker.is_alive():
            worker.cancel()
            if panel not in self._retiring_panels:
                self._retiring_panels.append(panel)
        elif worker is not None:
            worker.join()
            panel._retiring = False
        self._sync_primary_aliases()
        self.request_render(immediate=True)

    def install_source(
        self,
        source: ContentSource,
        *,
        description: str = "Content in progress",
    ) -> None:
        """Schedule replacement after the previous source has really stopped."""
        panel = self._menu._primary_content_panel
        if panel is None:
            panel = self._menu.add_content_source(source, description=description)
            self._menu._primary_content_panel = panel
            return
        self._menu.set_content_panel_description(panel, description)
        self.replace_content_panel(panel, source)
        self._pending_source = (source, description)

    def _apply_source(self, source: ContentSource, description: str) -> None:
        """Install a source once no previous worker can still execute."""
        panel = self._menu._primary_content_panel
        if panel is None:
            panel = self._menu.add_content_source(source, description=description)
            self._menu._primary_content_panel = panel
            return
        panel._description = description
        self._apply_panel_source(panel, source)

    def close(self) -> None:
        """Cancel and join source work before releasing selectable resources."""
        if self._closed:
            return

        self._closed = True
        self._pending_source = None
        panels = tuple(
            dict.fromkeys((*self._menu.content_panels, *self._retiring_panels))
        )
        for panel in panels:
            if panel._worker is not None:
                panel._worker.cancel()
        for panel in panels:
            if panel._worker is not None:
                panel._worker.join()

        self._selector.close()
        self._wakeup_reader.close()
        self._wakeup_writer.close()

    def _install_panel_worker(self, panel: ContentPanel) -> None:
        """Start the worker for one already-safe panel source."""
        self._generation += 1
        panel._generation = self._generation
        panel._worker = None
        panel._dynamic_in_flight = False
        panel._next_dynamic_at = self._clock()

        if panel._renderer.state == "static":
            return

        source = panel._renderer.source

        if not callable(source) and not hasattr(source, "__next__"):
            raise RuntimeError("Non-static content source cannot be consumed")

        panel._worker = SourceWorker(
            panel=panel,
            generation=self._generation,
            source=source,
            events=self._source_events,
            notify=self._notify_source,
            description=panel.description,
        )
        panel._worker.start()

    def _apply_panel_source(
        self,
        panel: ContentPanel,
        source: ContentSource,
    ) -> None:
        panel._source = source
        panel._pending_source = None
        panel._renderer = ContentRenderer(source)
        panel._viewport = None
        self._install_panel_worker(panel)
        if panel is self._menu._primary_content_panel:
            self._content_renderer = panel._renderer
            self._menu._content_renderer = panel._renderer
            self._terminal_renderer.set_content_renderer(panel._renderer)
        self._sync_primary_aliases()
        self.request_render(immediate=True)

    def _progress_source_replacement(self) -> None:
        """Install only the latest request after the cancelled worker exits."""
        self._progress_panel_transitions()

    def _progress_panel_transitions(self) -> None:
        for panel in tuple(self._retiring_panels):
            worker = panel._worker
            if worker is not None and worker.is_alive():
                continue
            if worker is not None:
                worker.join()
            panel._retiring = False
            self._retiring_panels.remove(panel)

        for panel in self._menu.content_panels:
            source = panel._pending_source
            if source is None:
                continue
            worker = panel._worker
            if worker is not None and worker.is_alive():
                continue
            if worker is not None:
                worker.join()
            self._apply_panel_source(panel, source)
        self._pending_source = None
        self._sync_primary_aliases()

    def _sync_primary_aliases(self) -> None:
        panel = self._menu._primary_content_panel
        if panel is None:
            self._source_worker = None
            self._dynamic_in_flight = False
            return
        self._content_renderer = panel._renderer
        self._source_worker = panel._worker
        self._dynamic_in_flight = panel._dynamic_in_flight
        self._next_dynamic_at = panel._next_dynamic_at

    def _clear_source_events(self) -> None:
        """Discard queued results belonging to a replaced source."""
        while True:
            try:
                self._source_events.get_nowait()
            except Empty:
                return

    def _drain_input(self) -> None:
        """Handle every input event immediately available from the terminal."""
        while True:
            event = self._input_handler.poll()

            if event is None:
                return

            self._menu._handle_event(event)
            self.request_render()

            if not self._menu._running:
                return

    def _drain_source_events(self) -> None:
        """Apply current-generation events to their corresponding panels."""
        grouped: dict[ContentPanel, list[SourceEvent]] = {}
        known = {*self._menu.content_panels, *self._retiring_panels}

        while True:
            try:
                event = self._source_events.get_nowait()
            except Empty:
                break

            if event.panel in known and event.generation == event.panel._generation:
                grouped.setdefault(event.panel, []).append(event)

        if not grouped:
            return

        for panel, events in grouped.items():
            renderer = panel._renderer
            if renderer.state == "streaming":
                chunks = [
                    event.value
                    for event in events
                    if event.kind == "data" and isinstance(event.value, str)
                ]
                if chunks:
                    renderer.append_stream_batch(chunks)
                    self._terminal_renderer.apply_stream_auto_scroll(
                        panel.auto_scroll,
                        panel,
                    )
                    self.request_render()
            elif renderer.state == "dynamic":
                values = [event.value for event in events if event.kind == "data"]
                if values:
                    value = values[-1]
                    if not isinstance(value, (str, list)):
                        raise RuntimeError("Dynamic worker returned invalid content")
                    renderer.replace_dynamic_content(value)
                    self.request_render()
                panel._dynamic_in_flight = False

            for event in events:
                self._handle_source_event(event)
        self._sync_primary_aliases()

    def _handle_source_event(self, event: SourceEvent) -> None:
        """Handle completion and failures after applying source data."""
        if event.kind == "complete":
            event.panel._renderer.finish_stream()
            self.request_render()
            return

        if event.kind == "error":
            if event.error is None:
                raise RuntimeError("Source failure event has no exception")

            raise event.error.with_traceback(event.traceback)

    def _request_dynamic_update(self) -> None:
        """Request one dynamic result when no evaluation is in flight."""
        self._request_dynamic_updates()

    def _request_dynamic_updates(self) -> None:
        """Request due evaluations independently for every dynamic panel."""
        now = self._clock()
        for panel in self._menu.content_panels:
            worker = panel._worker
            if (
                panel._renderer.state != "dynamic"
                or worker is None
                or panel._dynamic_in_flight
                or now < panel._next_dynamic_at
            ):
                continue
            panel._dynamic_in_flight = True
            panel._next_dynamic_at = now + self._FRAME_INTERVAL
            worker.request_dynamic_update()
        self._sync_primary_aliases()

    def _render_if_due(self) -> None:
        """Render dirty state no faster than the configured frame interval."""
        now = self._clock()

        if not self._dirty or now < self._next_frame_at:
            return

        self._menu_renderer.update()
        self._terminal_renderer.render()
        self._dirty = False
        self._next_frame_at = now + self._FRAME_INTERVAL

    def _get_wait_timeout(self) -> float:
        """Return the delay until the next scheduled loop responsibility."""
        now = self._clock()
        deadlines = [self._next_state_check_at]

        if self._dirty:
            deadlines.append(self._next_frame_at)

        input_timeout = self._input_handler.get_pending_timeout(now)

        if input_timeout is not None:
            deadlines.append(now + input_timeout)

        deadlines.extend(
            panel._next_dynamic_at
            for panel in self._menu.content_panels
            if panel._renderer.state == "dynamic" and not panel._dynamic_in_flight
        )

        return max(0.0, min(deadlines) - now)

    def _check_visible_state(self) -> None:
        """Detect screen-context and terminal-size changes at a fixed cadence."""
        now = self._clock()

        if now < self._next_state_check_at:
            return

        revision = self._menu_renderer.revision
        self._menu_renderer.update()

        if self._menu_renderer.revision != revision:
            self.request_render()

        if self._menu._tick_task_exit(now):
            self.request_render()

        terminal_size = get_terminal_size()

        if terminal_size != self._terminal_size:
            self._terminal_size = terminal_size
            self.request_render(immediate=True)

        self._next_state_check_at = now + self._STATE_CHECK_INTERVAL

    def _notify_source(self) -> None:
        """Wake the selector after publishing a source event."""
        try:
            self._wakeup_writer.send(b"\0")
        except (BlockingIOError, OSError):
            pass

    def _drain_wakeup(self) -> None:
        """Discard every coalesced source wakeup byte."""
        while True:
            try:
                if not self._wakeup_reader.recv(256):
                    return
            except BlockingIOError:
                return
