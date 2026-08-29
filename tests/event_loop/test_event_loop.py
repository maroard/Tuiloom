from __future__ import annotations

from collections.abc import Callable, Iterator
from selectors import BaseSelector, SelectorKey
from threading import Event, Thread
from typing import cast

import pytest

from tuiloom import KeyBinding, ScreenContext, TerminalApp, TerminalMenu
from tuiloom.event_loop.event_loop import EventLoop
from tuiloom.event_loop.source_event import SourceEvent
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.render.content_renderer import ContentRenderer, ContentSource
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer


class FakeSelector:
    def __init__(self) -> None:
        self.registered: list[object] = []
        self.ready: list[tuple[SelectorKey, int]] = []
        self.timeouts: list[float | None] = []
        self.closed = False

    def register(self, fileobj: object, events: int, data: object) -> None:
        self.registered.append(fileobj)

    def select(self, timeout: float | None = None) -> list[tuple[SelectorKey, int]]:
        self.timeouts.append(timeout)
        ready, self.ready = self.ready, []
        return ready

    def close(self) -> None:
        self.closed = True


class FakeInput:
    def __init__(self, events: list[InputEvent | None]) -> None:
        self.events = events

    def fileno(self) -> int:
        return 0

    def poll(self) -> InputEvent | None:
        return self.events.pop(0) if self.events else None

    def get_pending_timeout(self, now: float) -> float | None:
        return None


class BlockingIterator:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.finished = False

    def __iter__(self) -> BlockingIterator:
        return self

    def __next__(self) -> str:
        if self.finished:
            raise StopIteration
        self.started.set()
        self.release.wait(1)
        self.finished = True
        raise StopIteration

    def cancel(self) -> None:
        self.release.set()


def make_loop(
    events: list[InputEvent | None],
    *,
    content: ContentSource = "content",
    clock: Callable[[], float] = lambda: 0.0,
) -> tuple[TerminalMenu, EventLoop, FakeSelector, TerminalRenderer]:
    app = TerminalApp("App")
    menu = TerminalMenu(
        app,
        ScreenContext("main", "Main"),
        content_source=content,
    )
    menu._running = True
    menu.add_command("Stop", lambda context: menu._stop_immediately())
    content_renderer = ContentRenderer(content)
    menu_renderer = MenuRenderer(menu)
    terminal_renderer = TerminalRenderer(
        menu=menu,
        menu_renderer=menu_renderer,
        content_renderer=content_renderer,
        content_spacing=True,
    )
    selector = FakeSelector()
    loop = EventLoop(
        menu,
        cast(InputHandler, FakeInput(events)),
        menu_renderer,
        terminal_renderer,
        content_renderer,
        clock=clock,
        selector_factory=lambda: cast(BaseSelector, selector),
    )
    menu._event_loop = loop
    return menu, loop, selector, terminal_renderer


def test_event_loop_drains_immediate_input_and_stops() -> None:
    menu, loop, _, _ = make_loop([InputEvent(KeyBinding("enter")), None])
    loop.run_once()
    assert not menu._running
    loop.close()


def test_event_loop_detects_context_and_terminal_state_changes() -> None:
    menu, loop, _, renderer = make_loop([None])
    menu.screen_context.message = "changed"
    loop._check_visible_state()
    assert loop._dirty
    renderer.invalidate()
    loop.close()
    loop.close()


def test_install_source_replaces_menu_and_terminal_renderers() -> None:
    menu, loop, _, renderer = make_loop([None])
    old = menu._content_renderer
    loop.install_source("new")
    assert menu._content_renderer is not old
    assert renderer._content_renderer is menu._content_renderer
    loop.close()


def test_streaming_events_apply_data_completion_and_ignore_stale() -> None:
    menu, loop, _, renderer = make_loop([None])
    streaming = ContentRenderer(iter([]))
    panel = menu.content_panels[0]
    panel._renderer = streaming
    loop._content_renderer = streaming
    menu._content_renderer = streaming
    renderer.set_content_renderer(streaming)
    loop._source_events.put(SourceEvent(panel, loop._generation - 1, "data", "stale"))
    loop._source_events.put(SourceEvent(panel, loop._generation, "data", "fresh\n"))
    loop._source_events.put(SourceEvent(panel, loop._generation, "complete"))
    loop._drain_source_events()
    assert streaming.rendered_content.lines == ["fresh"]
    assert streaming.rendered_content.finished
    loop.close()


def test_dynamic_events_keep_latest_value_and_validate_results() -> None:
    menu, loop, _, renderer = make_loop([None])
    dynamic = ContentRenderer(lambda: "first")
    panel = menu.content_panels[0]
    panel._renderer = dynamic
    panel._dynamic_in_flight = True
    loop._content_renderer = dynamic
    menu._content_renderer = dynamic
    renderer.set_content_renderer(dynamic)
    loop._dynamic_in_flight = True
    loop._source_events.put(SourceEvent(panel, loop._generation, "data", "old"))
    loop._source_events.put(SourceEvent(panel, loop._generation, "data", ["new"]))
    loop._drain_source_events()
    assert dynamic.rendered_content.lines == ["new"]
    assert not loop._dynamic_in_flight

    loop._source_events.put(
        SourceEvent(panel, loop._generation, "data", 3)  # type: ignore[arg-type]
    )
    with pytest.raises(RuntimeError, match="invalid"):
        loop._drain_source_events()
    loop.close()


def test_source_errors_are_raised_with_validation() -> None:
    menu, loop, _, _ = make_loop([None])
    panel = menu.content_panels[0]
    error = ValueError("source failed")
    with pytest.raises(ValueError, match="source failed"):
        loop._handle_source_event(
            SourceEvent(panel, loop._generation, "error", error=error)
        )
    with pytest.raises(RuntimeError, match="no exception"):
        loop._handle_source_event(SourceEvent(panel, loop._generation, "error"))
    loop.close()


def test_events_are_routed_to_their_own_panels() -> None:
    menu, loop, _, _ = make_loop([None], content=iter(()))
    first = menu.content_panels[0]
    second = menu.add_content_source(iter(()), description="Second")

    loop._source_events.put(SourceEvent(first, first._generation, "data", "first\n"))
    loop._source_events.put(SourceEvent(second, second._generation, "data", "second\n"))
    loop._drain_source_events()

    assert first._renderer.rendered_content.lines == ["first"]
    assert second._renderer.rendered_content.lines == ["second"]
    loop.close()


def test_active_removal_hides_panel_but_tracks_worker_until_termination() -> None:
    menu, loop, _, _ = make_loop([None], content="primary")
    source = BlockingIterator()
    panel = menu.add_content_source(source, description="Blocking")
    assert source.started.wait(1)

    menu.remove_content_panel(panel)

    assert panel not in menu.content_panels
    assert panel in loop.retiring_panels
    assert panel._worker is not None
    assert panel._worker.join(1)
    loop._progress_panel_transitions()
    assert panel not in loop.retiring_panels
    loop.close()


def test_active_replacement_waits_for_old_worker_before_starting_new() -> None:
    menu, loop, _, _ = make_loop([None], content="primary")
    old = BlockingIterator()
    panel = menu.add_content_source(old, description="Work")
    assert old.started.wait(1)
    replacement = iter(["new\n"])

    menu.set_content_panel_source(panel, replacement)

    assert panel._pending_source is replacement
    assert panel._renderer.source is old
    assert panel._worker is not None
    assert panel._worker.join(1)
    loop._progress_panel_transitions()
    assert panel._renderer.source is replacement
    loop.close()


def test_panel_error_is_propagated_and_close_joins_other_workers() -> None:
    menu, loop, _, _ = make_loop([None], content="primary")
    blocking = BlockingIterator()
    other = menu.add_content_source(blocking, description="Other")
    assert blocking.started.wait(1)
    failed = menu.add_content_source("failed", description="Failed")
    error = ValueError("panel failed")
    loop._source_events.put(
        SourceEvent(
            failed,
            failed._generation,
            "error",
            error=error,
            traceback=error.__traceback__,
        )
    )

    with pytest.raises(ValueError, match="panel failed"):
        loop._drain_source_events()
    loop.close()

    assert other._worker is not None
    assert not other._worker.is_alive()


def test_completed_temporary_output_panel_is_removed_after_final_chunks() -> None:
    menu, loop, _, _ = make_loop([None], content="primary")
    panel = menu.add_content_source(iter(()), description="Output")
    panel._remove_when_finished = True
    panel._renderer.append_stream_batch(["final\n"])
    loop._source_events.put(SourceEvent(panel, panel._generation, "complete"))

    loop._drain_source_events()

    assert panel._renderer.rendered_content.lines == ["final"]
    assert panel not in menu.content_panels
    loop.close()


def test_render_deadlines_and_run_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    menu, loop, selector, renderer = make_loop(
        [InputEvent(KeyBinding("enter")), None], clock=lambda: now[0]
    )
    renders: list[None] = []
    monkeypatch.setattr(renderer, "render", lambda: renders.append(None))
    loop.request_render(immediate=True)
    loop._render_if_due()
    assert renders == [None]
    loop._render_if_due()
    assert renders == [None]
    menu._running = True
    loop.run()
    assert not menu._running
    assert selector.timeouts
    loop.close()


def test_wakeup_socket_is_drained_without_blocking() -> None:
    _, loop, _, _ = make_loop([None])
    loop._notify_source()
    loop._drain_wakeup()
    loop._drain_source_events()
    loop.close()


def test_source_replacement_waits_and_only_starts_latest_request() -> None:
    _, loop, _, _ = make_loop([None])
    old_started = Event()
    old_release = Event()
    second_started = Event()
    latest_started = Event()
    latest_release = Event()

    def old_source() -> Iterator[str]:
        old_started.set()
        old_release.wait()
        yield "old"

    def second_source() -> Iterator[str]:
        second_started.set()
        yield "second"

    def latest_source() -> Iterator[str]:
        latest_started.set()
        latest_release.wait()
        yield "latest"

    loop.install_source(old_source(), description="Old")
    assert old_started.wait(1)

    loop.install_source(
        second_source(),
        description="Second",
    )
    loop.install_source(
        latest_source(),
        description="Latest",
    )

    assert not second_started.is_set()
    assert not latest_started.is_set()
    old_release.set()
    assert loop._source_worker is not None
    assert loop._source_worker.join(1)

    loop._progress_source_replacement()

    assert latest_started.wait(1)
    assert not second_started.is_set()
    assert loop.active_work is not None
    assert loop.active_work.description == "Latest"
    latest_release.set()
    loop.close()
    assert loop._source_worker is not None
    assert not loop._source_worker.is_alive()


def test_close_waits_for_cancelled_iterator_before_closing_resources() -> None:
    _, loop, selector, _ = make_loop([None])
    started = Event()
    release = Event()

    def blocked() -> Iterator[str]:
        started.set()
        release.wait()
        yield "late"

    loop.install_source(blocked())
    assert started.wait(1)
    worker = loop._source_worker
    assert worker is not None
    closer = Thread(target=loop.close)
    closer.start()

    assert closer.is_alive()
    assert not selector.closed
    release.set()
    closer.join(1)

    assert not closer.is_alive()
    assert not worker.is_alive()
    assert selector.closed


def test_dynamic_source_is_active_only_during_evaluation_and_close_joins_it() -> None:
    _, loop, _, _ = make_loop([None])
    started = Event()
    release = Event()

    def dynamic() -> str:
        started.set()
        release.wait()
        return "done"

    loop.install_source(dynamic, description="Refreshing")
    assert loop.active_work is None
    loop._request_dynamic_update()
    assert started.wait(1)
    assert loop.active_work is not None
    assert loop.active_work.description == "Refreshing"

    closer = Thread(target=loop.close)
    closer.start()
    assert closer.is_alive()
    release.set()
    closer.join(1)

    assert not closer.is_alive()
    assert loop._source_worker is not None
    assert not loop._source_worker.is_alive()
