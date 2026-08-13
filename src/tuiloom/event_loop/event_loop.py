from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Queue
from selectors import EVENT_READ, BaseSelector, DefaultSelector
from shutil import get_terminal_size
from socket import socketpair
from time import monotonic
from typing import TYPE_CHECKING

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
        self.menu = menu
        self.input_handler = input_handler
        self.menu_renderer = menu_renderer
        self.terminal_renderer = terminal_renderer
        self.content_renderer = content_renderer
        self._clock = clock
        self._selector = selector_factory()
        self._wakeup_reader, self._wakeup_writer = socketpair()
        self._wakeup_reader.setblocking(False)
        self._wakeup_writer.setblocking(False)
        self._selector.register(input_handler.fileno(), EVENT_READ, "input")
        self._selector.register(self._wakeup_reader, EVENT_READ, "source")

        self.source_events: Queue[SourceEvent] = Queue(maxsize=self._SOURCE_QUEUE_SIZE)
        self.generation = 0
        self._source_worker: SourceWorker | None = None
        self._dirty = True
        now = self._clock()
        self._next_frame_at = now
        self._next_state_check_at = now
        self._dynamic_in_flight = False
        self._next_dynamic_at = now
        self._terminal_size = get_terminal_size()
        self._closed = False

        self._install_worker(content_renderer)

    def run(self) -> None:
        """Process events until the owning menu stops."""
        while self.menu.running:
            self.run_once()

    def run_once(self) -> None:
        """Process one selectable event-loop turn."""
        ready = self._selector.select(self._get_wait_timeout())

        for key, _ in ready:
            if key.data == "source":
                self._drain_wakeup()
                self._drain_source_events()

        self._drain_input()
        self._request_dynamic_update()
        self._check_visible_state()
        self._render_if_due()

    def request_render(self, immediate: bool = False) -> None:
        """Mark visible state dirty for the next permitted frame."""
        self._dirty = True

        if immediate:
            self._next_frame_at = self._clock()

    def install_source(self, source: ContentSource) -> None:
        """Replace the active source and discard every stale source event."""
        content_renderer = ContentRenderer(source)
        self.content_renderer = content_renderer
        self.menu.content_renderer = content_renderer
        self.terminal_renderer.set_content_renderer(content_renderer)
        self._install_worker(content_renderer)
        self.request_render(immediate=True)

    def close(self) -> None:
        """Release event-loop resources without waiting on blocked source code."""
        if self._closed:
            return

        self._closed = True

        if self._source_worker is not None:
            self._source_worker.cancel()

        self._selector.close()
        self._wakeup_reader.close()
        self._wakeup_writer.close()

    def _install_worker(self, content_renderer: ContentRenderer) -> None:
        """Cancel the old generation and start the new source when required."""
        if self._source_worker is not None:
            self._source_worker.cancel()

        self.generation += 1
        self._clear_source_events()
        self._source_worker = None
        self._dynamic_in_flight = False

        if content_renderer.state == "static":
            return

        source = content_renderer.source

        if not callable(source) and not hasattr(source, "__next__"):
            raise RuntimeError("Non-static content source cannot be consumed")

        self._source_worker = SourceWorker(
            generation=self.generation,
            source=source,
            events=self.source_events,
            notify=self._notify_source,
        )
        self._source_worker.start()

    def _clear_source_events(self) -> None:
        """Discard queued results belonging to a replaced source."""
        while True:
            try:
                self.source_events.get_nowait()
            except Empty:
                return

    def _drain_input(self) -> None:
        """Handle every input event immediately available from the terminal."""
        while True:
            event = self.input_handler.poll()

            if event is None:
                return

            self.menu._handle_event(event)
            self.request_render()

            if not self.menu.running:
                return

    def _drain_source_events(self) -> None:
        """Apply every current generation event as one content update batch."""
        events: list[SourceEvent] = []

        while True:
            try:
                event = self.source_events.get_nowait()
            except Empty:
                break

            if event.generation == self.generation:
                events.append(event)

        if not events:
            return

        if self.content_renderer.state == "streaming":
            chunks = [
                event.value
                for event in events
                if event.kind == "data" and isinstance(event.value, str)
            ]

            if chunks:
                self.content_renderer.append_stream_batch(chunks)
                self.terminal_renderer.apply_stream_auto_scroll(
                    self.menu.auto_scroll
                )
                self.request_render()

        elif self.content_renderer.state == "dynamic":
            values = [event.value for event in events if event.kind == "data"]

            if values:
                value = values[-1]

                if not isinstance(value, (str, list)):
                    raise RuntimeError("Dynamic worker returned invalid content")

                self.content_renderer.replace_dynamic_content(value)
                self.request_render()

            self._dynamic_in_flight = False

        for event in events:
            self._handle_source_event(event)

    def _handle_source_event(self, event: SourceEvent) -> None:
        """Handle completion and failures after applying source data."""
        if event.kind == "complete":
            self.content_renderer.finish_stream()
            self.request_render()
            return

        if event.kind == "error":
            if event.error is None:
                raise RuntimeError("Source failure event has no exception")

            raise event.error.with_traceback(event.traceback)

    def _request_dynamic_update(self) -> None:
        """Request one dynamic result when no evaluation is in flight."""
        if (
            self.content_renderer.state != "dynamic"
            or self._source_worker is None
            or self._dynamic_in_flight
            or self._clock() < self._next_dynamic_at
        ):
            return

        self._dynamic_in_flight = True
        self._next_dynamic_at = self._clock() + self._FRAME_INTERVAL
        self._source_worker.request_dynamic_update()

    def _render_if_due(self) -> None:
        """Render dirty state no faster than the configured frame interval."""
        now = self._clock()

        if not self._dirty or now < self._next_frame_at:
            return

        self.menu_renderer.update_screen_context(self.menu.screen_context)
        self.terminal_renderer.render(self.menu._input_buffer)
        self._dirty = False
        self._next_frame_at = now + self._FRAME_INTERVAL

    def _get_wait_timeout(self) -> float:
        """Return the delay until the next scheduled loop responsibility."""
        now = self._clock()
        deadlines = [self._next_state_check_at]

        if self._dirty:
            deadlines.append(self._next_frame_at)

        input_timeout = self.input_handler.get_pending_timeout(now)

        if input_timeout is not None:
            deadlines.append(now + input_timeout)

        if self.content_renderer.state == "dynamic" and not self._dynamic_in_flight:
            deadlines.append(self._next_dynamic_at)

        return max(0.0, min(deadlines) - now)

    def _check_visible_state(self) -> None:
        """Detect screen-context and terminal-size changes at a fixed cadence."""
        now = self._clock()

        if now < self._next_state_check_at:
            return

        revision = self.menu_renderer.revision
        self.menu_renderer.update_screen_context(self.menu.screen_context)

        if self.menu_renderer.revision != revision:
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
