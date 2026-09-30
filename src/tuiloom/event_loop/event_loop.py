from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Queue
from selectors import EVENT_READ, BaseSelector, DefaultSelector
from shutil import get_terminal_size
from socket import socketpair
from time import monotonic
from typing import TYPE_CHECKING

from tuiloom.animation import AnimationFrame, AnimationTimeline
from tuiloom.background_work import BackgroundWork
from tuiloom.cleanup import run_cleanup
from tuiloom.content_panel import ContentPanel
from tuiloom.event_loop.source_event import SourceEvent
from tuiloom.event_loop.source_worker import SourceWorker, WorkerSource
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.screen_content import ContentSize, ScreenContent

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
        *,
        clock: Callable[[], float] = monotonic,
        selector_factory: Callable[[], BaseSelector] = DefaultSelector,
    ) -> None:
        """Create an event loop over initialized menu renderers."""
        self._menu = menu
        self._input_handler = input_handler
        self._menu_renderer = menu_renderer
        self._terminal_renderer = terminal_renderer
        self._clock = clock
        self._closed = False
        resources: list[Callable[[], object]] = []
        attempted_panels: list[ContentPanel] = []
        try:
            self._selector = selector_factory()
            resources.append(self._selector.close)
            self._wakeup_reader, self._wakeup_writer = socketpair()
            resources.extend((self._wakeup_reader.close, self._wakeup_writer.close))
            self._wakeup_reader.setblocking(False)
            self._wakeup_writer.setblocking(False)
            self._selector.register(input_handler.fileno(), EVENT_READ, "input")
            self._selector.register(self._wakeup_reader, EVENT_READ, "source")

            self._source_events: Queue[SourceEvent] = Queue(
                maxsize=self._SOURCE_QUEUE_SIZE
            )
            self._retiring_panels: list[ContentPanel] = []
            self._dirty = True
            now = self._clock()
            self._animation_timeline = AnimationTimeline(now)
            self._animation_active = True
            self._last_ui_animation: tuple[tuple[float, int], ...] | None = None
            self._next_frame_at = now
            self._next_state_check_at = now
            self._terminal_size = get_terminal_size()

            for panel in menu.content_panels:
                attempted_panels.append(panel)
                self._install_panel_worker(panel)
        except BaseException as error:
            self._closed = True
            workers = tuple(
                dict.fromkeys(
                    panel._runtime.worker
                    for panel in attempted_panels
                    if panel._runtime.worker is not None
                )
            )
            try:
                run_cleanup(
                    (
                        *(worker.cancel for worker in workers),
                        *(worker.join for worker in workers),
                        *resources,
                    ),
                    message="Errors while rolling back event-loop initialization",
                    prior_error=error,
                )
            finally:
                for panel in attempted_panels:
                    worker = panel._runtime.worker
                    if worker is not None and not worker.is_alive():
                        panel._runtime.worker = None
            raise

    def run(self) -> None:
        """Process events until the owning menu stops."""
        while self._menu._running:
            self.run_once()

    def run_once(
        self,
        *,
        process_input: bool = True,
        render: bool = True,
        block: bool = True,
    ) -> None:
        """Process one turn, optionally limiting it to background work."""
        self._progress_panel_transitions()
        ready = self._selector.select(self._get_wait_timeout() if block else 0)

        for key, _ in ready:
            if key.data == "source":
                self._drain_wakeup()
        self._drain_source_events()

        if process_input:
            self._drain_input()
        self._request_dynamic_updates()
        completed_menu = self._menu.app._dispatch_output_task_outcome()

        if completed_menu is self._menu:
            self.request_render(immediate=True)

        self._check_visible_state()
        if render and (
            not self._menu.app._menu_stack
            or self._menu.app._menu_stack[-1] is self._menu
        ):
            self._render_if_due()

    def request_render(self, immediate: bool = False) -> None:
        """Mark visible state dirty for the next permitted frame."""
        self._dirty = True

        if immediate:
            self._next_frame_at = self._clock()

    def set_animation_active(self, active: bool) -> None:
        """Pause covered-menu animations and resume their active-time phase."""
        if self._animation_active == active:
            return
        self._animation_timeline.set_active(active, self._clock())
        self._animation_active = active
        if active:
            self.request_render(immediate=True)

    @property
    def active_work(self) -> BackgroundWork | None:
        """Return source work that currently prevents a safe menu exit."""
        active = self.active_panels
        return active[0]._runtime.worker if active else None

    @property
    def active_panels(self) -> tuple[ContentPanel, ...]:
        """Return logical panels whose work currently blocks safe exit."""
        return tuple(
            panel
            for panel in dict.fromkeys(
                (*self._menu.content_panels, *self._retiring_panels)
            )
            if panel._runtime.blocks_exit
        )

    @property
    def retiring_panels(self) -> tuple[ContentPanel, ...]:
        """Return removed panels whose workers have not terminated yet."""
        return tuple(self._retiring_panels)

    def add_content_panel(self, panel: ContentPanel) -> None:
        """Start runtime work for a panel added while the loop is active."""
        self._install_panel_worker(panel)
        self.request_render(immediate=True)

    def update_content_panel_size(
        self,
        panel: ContentPanel,
        size: ContentSize,
    ) -> None:
        """Record layout geometry and request responsive work when required."""
        previous = panel._runtime.effective_size
        panel._runtime.effective_size = size
        if panel._runtime.renderer.state not in ("responsive", "animated"):
            return
        if previous != size or panel._runtime.responsive_refresh_pending:
            if panel._runtime.renderer.state == "animated":
                self._request_animated_update(panel, size)
            else:
                self._request_responsive_update(panel, size)

    def refresh_content_panel(self, panel: ContentPanel) -> None:
        """Request an immediate responsive result, if layout is known."""
        size = panel._runtime.effective_size
        if size is None:
            panel._runtime.responsive_refresh_pending = True
            self.request_render(immediate=True)
            return
        if panel._runtime.renderer.state == "animated":
            self._request_animated_update(panel, size)
        else:
            self._request_responsive_update(panel, size)

    def _request_animated_update(
        self, panel: ContentPanel, size: ContentSize, *, force: bool = True
    ) -> None:
        """Request one numbered frame using the shared active-time timeline."""
        worker = panel._runtime.worker
        fps = panel._content.fps
        if fps is None:
            raise RuntimeError("Animated content rate is missing")
        if worker is None or self._refreshes_suspended() or not self._animation_active:
            panel._runtime.responsive_refresh_pending = True
            panel._runtime.next_dynamic_at = self._clock()
            return
        now = self._clock()
        elapsed = self._animation_timeline.elapsed(now)
        frame = AnimationFrame(elapsed, int(elapsed * fps + 1e-9))
        if not force and panel._runtime.last_animation_index == frame.index:
            panel._runtime.next_dynamic_at = now + max(
                0.0, (frame.index + 1) / fps - elapsed
            )
            return
        panel._runtime.responsive_refresh_pending = False
        panel._runtime.last_animation_index = frame.index
        panel._runtime.responsive_request_id += 1
        panel._runtime.dynamic_in_flight = True
        panel._runtime.next_dynamic_at = now + max(
            0.0, (frame.index + 1) / fps - elapsed
        )
        worker.request_animated_update(
            panel._runtime.responsive_request_id, size, frame
        )

    def _request_responsive_update(
        self,
        panel: ContentPanel,
        size: ContentSize,
    ) -> None:
        """Request responsive content, deferring refreshes while exit waits."""
        worker = panel._runtime.worker
        if worker is None or self._refreshes_suspended():
            panel._runtime.responsive_refresh_pending = True
            return
        panel._runtime.responsive_refresh_pending = False
        panel._runtime.responsive_request_id += 1
        panel._runtime.dynamic_in_flight = True
        panel._runtime.next_dynamic_at = self._clock() + self._FRAME_INTERVAL
        worker.request_responsive_update(panel._runtime.responsive_request_id, size)

    def replace_content_panel(
        self,
        panel: ContentPanel,
        content: ScreenContent,
    ) -> None:
        """Replace one panel only after its previous worker terminates."""
        panel._runtime.request_replacement(content)
        worker = panel._runtime.worker
        if worker is not None and worker.is_alive():
            worker.cancel()
            self._notify_source()
        else:
            if worker is not None:
                worker.join()
            self._apply_panel_content(panel, content)
        self.request_render(immediate=True)

    def retire_content_panel(self, panel: ContentPanel) -> None:
        """Cancel and track a removed panel until its worker stops."""
        panel._runtime.begin_retirement()
        self._menu.app._prune_stream_claims(panel)
        worker = panel._runtime.worker
        if worker is not None and worker.is_alive():
            if panel not in self._retiring_panels:
                self._retiring_panels.append(panel)
            worker.cancel()
        elif worker is not None:
            worker.join()
            panel._runtime.retiring = False
            self._menu.app._release_stream_claims(panel)
        else:
            panel._runtime.retiring = False
            self._menu.app._release_stream_claims(panel)
        self.request_render(immediate=True)

    def close(self) -> None:
        """Cancel and join source work before releasing selectable resources."""
        if self._closed:
            return

        self._closed = True
        panels = tuple(
            dict.fromkeys((*self._menu.content_panels, *self._retiring_panels))
        )
        workers = tuple(
            dict.fromkeys(
                panel._runtime.worker
                for panel in panels
                if panel._runtime.worker is not None
            )
        )
        try:
            run_cleanup(
                (
                    *(worker.cancel for worker in workers),
                    *(worker.join for worker in workers),
                    self._selector.close,
                    self._wakeup_reader.close,
                    self._wakeup_writer.close,
                ),
                message="Errors while closing content workers and event-loop resources",
            )
        finally:
            for panel in tuple(self._retiring_panels):
                worker = panel._runtime.worker
                if worker is not None and worker.is_alive():
                    continue
                panel._runtime.retiring = False
                self._menu.app._release_stream_claims(panel)
                self._retiring_panels.remove(panel)

    def abandon(self) -> None:
        """Release selectable resources without touching application workers."""
        if self._closed:
            return

        self._closed = True
        self._close_resources()

    def _close_resources(self) -> None:
        """Close the selector and wakeup sockets exactly once."""
        run_cleanup(
            (
                self._selector.close,
                self._wakeup_reader.close,
                self._wakeup_writer.close,
            ),
            message="Errors while closing event-loop resources",
        )

    def _install_panel_worker(self, panel: ContentPanel) -> None:
        """Start the worker for one already-safe panel source."""
        panel._runtime.generation += 1
        panel._runtime.worker = None
        panel._runtime.dynamic_in_flight = False
        panel._runtime.next_dynamic_at = self._clock()

        if panel._runtime.renderer.state == "static":
            return

        content = panel._content
        source: WorkerSource
        if panel._runtime.renderer.state == "streaming":
            source = content._stream()
        elif panel._runtime.renderer.state == "dynamic":
            source = content._dynamic()
        elif panel._runtime.renderer.state == "responsive":
            source = content._responsive()
        elif panel._runtime.renderer.state == "animated":
            source = content._animated()
        else:
            raise RuntimeError("Non-static screen content cannot be consumed")

        panel._runtime.worker = SourceWorker(
            panel=panel,
            generation=panel._runtime.generation,
            kind=panel._runtime.renderer.state,
            source=source,
            events=self._source_events,
            notify=self._notify_source,
            description=panel.description,
        )
        panel._runtime.worker.start()

    def _apply_panel_content(
        self,
        panel: ContentPanel,
        content: ScreenContent,
    ) -> None:
        panel._restore_selection(content)
        panel._content = content
        panel._runtime.mount(content)
        self._install_panel_worker(panel)
        self._menu.app._prune_stream_claims(panel)
        self.request_render(immediate=True)

    def _progress_panel_transitions(self) -> None:
        for panel in tuple(self._retiring_panels):
            worker = panel._runtime.worker
            if worker is not None and worker.is_alive():
                continue
            if worker is not None:
                worker.join()
            panel._runtime.retiring = False
            self._menu.app._release_stream_claims(panel)
            self._retiring_panels.remove(panel)

        for panel in self._menu.content_panels:
            content = panel._runtime.pending_content
            if content is None:
                continue
            worker = panel._runtime.worker
            if worker is not None and worker.is_alive():
                continue
            if worker is not None:
                worker.join()
            self._apply_panel_content(panel, content)

    def _drain_input(self) -> None:
        """Handle every input event immediately available from the terminal."""
        while True:
            event = self._input_handler.poll()

            if event is None:
                return

            if event.terminal_focus is not None:
                if event.terminal_focus:
                    # A tab can return at the same size with a damaged physical
                    # screen. Its logical cache no longer proves what is shown.
                    self._terminal_renderer.invalidate()
                    self.request_render(immediate=True)
                continue

            self._menu._handle_event(event)
            self.request_render()

            if (
                not self._menu._running
                or self._menu.app._menu_stack
                and self._menu.app._menu_stack[-1] is not self._menu
            ):
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

            if (
                event.panel not in known
                or event.generation != event.panel._runtime.generation
            ):
                continue
            if (
                event.panel._runtime.renderer.state in ("responsive", "animated")
                and event.request_id != event.panel._runtime.responsive_request_id
            ):
                continue
            grouped.setdefault(event.panel, []).append(event)

        if not grouped:
            return

        for panel, events in grouped.items():
            renderer = panel._runtime.renderer
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
                panel._runtime.dynamic_in_flight = False
            elif renderer.state in ("responsive", "animated"):
                values = [event.value for event in events if event.kind == "data"]
                if values:
                    value = values[-1]
                    if not isinstance(value, (str, list)):
                        raise RuntimeError("Generated worker returned invalid content")
                    renderer.replace_generated_content(value)
                    self.request_render()
                panel._runtime.dynamic_in_flight = False

            for event in events:
                self._handle_source_event(event)

    def _handle_source_event(self, event: SourceEvent) -> None:
        """Handle completion and failures after applying source data."""
        if event.kind == "complete":
            event.panel._runtime.renderer.finish_stream()
            if event.panel._runtime.remove_when_finished and not event.panel._removed:
                event.panel.remove()
            self.request_render()
            return

        if event.kind == "error":
            if event.error is None:
                raise RuntimeError("Source failure event has no exception")

            raise event.error.with_traceback(event.traceback)

    def _refreshes_suspended(self) -> bool:
        """Pause new evaluations while any menu in the app stack waits to exit."""
        return any(
            menu._task_exit is not None and menu._task_exit.mode == "waiting"
            for menu in (self._menu, *self._menu.app._menu_stack)
        )

    def _request_dynamic_updates(self) -> None:
        """Request due dynamic and continuous-responsive evaluations."""
        if self._refreshes_suspended():
            return
        now = self._clock()
        for panel in self._menu.content_panels:
            worker = panel._runtime.worker
            if (
                worker is None
                or panel._runtime.pending_content is not None
                or now < panel._runtime.next_dynamic_at
            ):
                continue
            if (
                panel._runtime.renderer.state == "dynamic"
                and not panel._runtime.dynamic_in_flight
            ):
                panel._runtime.dynamic_in_flight = True
                panel._runtime.next_dynamic_at = now + self._FRAME_INTERVAL
                worker.request_dynamic_update()
            elif (
                panel._runtime.renderer.state == "responsive"
                and not panel._runtime.dynamic_in_flight
                and (
                    panel._content.refresh_mode == "continuous"
                    or panel._runtime.responsive_refresh_pending
                )
                and panel._runtime.effective_size is not None
            ):
                self._request_responsive_update(panel, panel._runtime.effective_size)
            elif (
                panel._runtime.renderer.state == "animated"
                and self._animation_active
                and panel._runtime.effective_size is not None
            ):
                self._request_animated_update(
                    panel,
                    panel._runtime.effective_size,
                    force=panel._runtime.responsive_refresh_pending,
                )

    def _ui_animation_rates(self) -> tuple[float, ...]:
        """Return the distinct rates of visible text/status animations."""
        if not self._animation_active:
            return ()
        rates = list(self._menu_renderer.animation_rates())
        status = self._menu.status_bar
        if status is not None and status._kind == "animated" and status.fps is not None:
            rates.append(status.fps)
        return tuple(sorted(set(rates)))

    def _has_dynamic_status(self) -> bool:
        status = self._menu.status_bar
        stack = self._menu.app._menu_stack
        return (
            status is not None
            and status._kind == "dynamic"
            and (not stack or stack[-1] is self._menu)
        )

    def _render_if_due(self) -> None:
        """Render dirty state no faster than the configured frame interval."""
        now = self._clock()

        rates = self._ui_animation_rates()
        elapsed = self._animation_timeline.elapsed(now)
        ui_frame = (
            tuple((rate, int(elapsed * rate + 1e-9)) for rate in rates)
            if rates
            else None
        )
        if ui_frame is not None and ui_frame != self._last_ui_animation:
            self._dirty = True

        if (
            not self._dirty and not self._has_dynamic_status()
        ) or now < self._next_frame_at:
            return

        self._menu_renderer.set_animation_elapsed(elapsed)
        self._terminal_renderer.set_animation_elapsed(elapsed)
        self._terminal_renderer.render()
        self._dirty = False
        self._last_ui_animation = ui_frame
        self._next_frame_at = now + self._FRAME_INTERVAL

    def _get_wait_timeout(self) -> float:
        """Return the delay until the next scheduled loop responsibility."""
        now = self._clock()
        deadlines = [self._next_state_check_at]

        if self._dirty or self._has_dynamic_status():
            deadlines.append(self._next_frame_at)

        rates = self._ui_animation_rates()
        if rates:
            elapsed = self._animation_timeline.elapsed(now)
            for rate in rates:
                next_index = int(elapsed * rate + 1e-9) + 1
                deadlines.append(now + max(0.0, next_index / rate - elapsed))

        input_timeout = self._input_handler.get_pending_timeout(now)

        if input_timeout is not None:
            deadlines.append(now + input_timeout)

        if not self._refreshes_suspended():
            deadlines.extend(
                panel._runtime.next_dynamic_at
                for panel in self._menu.content_panels
                if (
                    panel._runtime.renderer.state == "dynamic"
                    or panel._runtime.renderer.state == "responsive"
                    and (
                        panel._content.refresh_mode == "continuous"
                        or panel._runtime.responsive_refresh_pending
                    )
                    and panel._runtime.effective_size is not None
                    or panel._runtime.renderer.state == "animated"
                    and self._animation_active
                    and panel._runtime.effective_size is not None
                )
                and (
                    panel._runtime.renderer.state == "animated"
                    or not panel._runtime.dynamic_in_flight
                )
                and panel._runtime.pending_content is None
            )

        return max(0.0, min(deadlines) - now)

    def _check_visible_state(self) -> None:
        """Detect display-state and terminal-size changes at a fixed cadence."""
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
