from __future__ import annotations

from collections.abc import Callable, Iterator
from os import terminal_size
from selectors import BaseSelector, SelectorKey
from threading import Event, Thread
from typing import cast

import pytest

from tuiloom import (
    ContentSize,
    KeyBinding,
    ScreenContent,
    ScreenContext,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.event_loop.event_loop import EventLoop
from tuiloom.event_loop.source_event import SourceEvent
from tuiloom.event_loop.source_worker import SourceWorker
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.render.content_renderer import ContentRenderer
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


class UnstoppableWork:
    def __init__(self) -> None:
        self.cancel_calls = 0
        self.join_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1

    def join(self, timeout: float | None = None) -> bool:
        self.join_calls += 1
        return False

    def is_alive(self) -> bool:
        return True


def make_loop(
    events: list[InputEvent | None],
    *,
    content: ScreenContent | None = None,
    clock: Callable[[], float] = lambda: 0.0,
) -> tuple[TerminalMenu, EventLoop, FakeSelector, TerminalRenderer]:
    app = TerminalApp("App")
    content = content if content is not None else ScreenContent.static("content")
    menu = TerminalMenu(app, ScreenContext("main", "Main"))
    menu.add_content_panel(content)
    menu._running = True
    menu.add_command("Stop", lambda context: menu._stop_immediately())
    menu_renderer = MenuRenderer(menu)
    terminal_renderer = TerminalRenderer(
        menu=menu,
        menu_renderer=menu_renderer,
        content_spacing=True,
    )
    selector = FakeSelector()
    loop = EventLoop(
        menu,
        cast(InputHandler, FakeInput(events)),
        menu_renderer,
        terminal_renderer,
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


def test_event_loop_stops_draining_input_when_callback_changes_top_menu() -> None:
    menu, loop, _, _ = make_loop(
        [InputEvent(KeyBinding("enter")), InputEvent(KeyBinding("down")), None]
    )
    child = TerminalMenu(menu.app, ScreenContext("child", "Child"))
    menu._commands[0]._behavior = lambda context: menu.app.push_menu(child)
    menu.app._menu_stack = [menu]

    loop.run_once()

    assert menu.app._menu_stack == [menu, child]
    assert menu._selected_index == 0
    loop.close()


def test_event_loop_detects_context_and_terminal_state_changes() -> None:
    menu, loop, _, renderer = make_loop([None])
    menu.screen_context.message = "changed"
    loop._check_visible_state()
    assert loop._dirty
    renderer.invalidate()
    loop.close()
    loop.close()


def test_panel_replacement_replaces_its_renderer_and_viewport() -> None:
    menu, loop, _, renderer = make_loop([None])
    panel = menu.content_panels[0]
    old = panel._renderer
    renderer._compose_frame(30, 20)
    assert panel._viewport is not None

    panel.set_content(ScreenContent.static("new"))

    assert panel._renderer is not old
    assert panel._renderer.content == ScreenContent.static("new")
    assert panel._viewport is None
    renderer._compose_frame(30, 20)
    assert panel._viewport is not None
    assert "new" in panel._viewport.render()
    loop.close()


def test_streaming_events_apply_data_completion_and_ignore_stale() -> None:
    menu, loop, _, renderer = make_loop([None])
    streaming = ContentRenderer(ScreenContent.stream(iter([])))
    panel = menu.content_panels[0]
    panel._renderer = streaming
    loop._source_events.put(SourceEvent(panel, panel._generation - 1, "data", "stale"))
    loop._source_events.put(SourceEvent(panel, panel._generation, "data", "fresh\n"))
    loop._source_events.put(SourceEvent(panel, panel._generation, "complete"))
    loop._drain_source_events()
    assert streaming.rendered_content.lines == ["fresh"]
    assert streaming.rendered_content.finished
    loop.close()


def test_dynamic_events_keep_latest_value_and_validate_results() -> None:
    menu, loop, _, renderer = make_loop([None])
    dynamic = ContentRenderer(ScreenContent.dynamic(lambda: "first"))
    panel = menu.content_panels[0]
    panel._renderer = dynamic
    panel._dynamic_in_flight = True
    loop._source_events.put(SourceEvent(panel, panel._generation, "data", "old"))
    loop._source_events.put(SourceEvent(panel, panel._generation, "data", ["new"]))
    loop._drain_source_events()
    assert dynamic.rendered_content.lines == ["new"]
    assert not panel._dynamic_in_flight

    loop._source_events.put(
        SourceEvent(panel, panel._generation, "data", 3)  # type: ignore[arg-type]
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
            SourceEvent(panel, panel._generation, "error", error=error)
        )
    with pytest.raises(RuntimeError, match="no exception"):
        loop._handle_source_event(SourceEvent(panel, panel._generation, "error"))
    loop.close()


def test_events_are_routed_to_their_own_panels() -> None:
    menu, loop, _, _ = make_loop([None], content=ScreenContent.stream(iter(())))
    first = menu.content_panels[0]
    second = menu.add_content_panel(
        ScreenContent.stream(iter(())), description="Second"
    )

    loop._source_events.put(SourceEvent(first, first._generation, "data", "first\n"))
    loop._source_events.put(SourceEvent(second, second._generation, "data", "second\n"))
    loop._drain_source_events()

    assert first._renderer.rendered_content.lines == ["first"]
    assert second._renderer.rendered_content.lines == ["second"]
    loop.close()


def test_active_removal_hides_panel_but_tracks_worker_until_termination() -> None:
    menu, loop, _, _ = make_loop([None], content=ScreenContent.static("primary"))
    source = BlockingIterator()
    panel = menu.add_content_panel(ScreenContent.stream(source), description="Blocking")
    assert source.started.wait(1)

    panel.remove()

    assert panel not in menu.content_panels
    assert panel in loop.retiring_panels
    assert panel._worker is not None
    assert panel._worker.join(1)
    loop._progress_panel_transitions()
    assert panel not in loop.retiring_panels
    loop.close()


def test_active_replacement_waits_for_old_worker_before_starting_new() -> None:
    menu, loop, _, _ = make_loop([None], content=ScreenContent.static("primary"))
    old = BlockingIterator()
    panel = menu.add_content_panel(ScreenContent.stream(old), description="Work")
    assert old.started.wait(1)
    replacement = ScreenContent.stream(iter(["new\n"]))

    panel.set_content(replacement)

    assert panel._pending_content is replacement
    assert panel._renderer.content._stream() is old
    assert panel._worker is not None
    assert panel._worker.join(1)
    panel._smart_auto_scroll_active = False
    panel._pending_auto_scroll = "strict"
    loop._progress_panel_transitions()
    assert panel._renderer.content is replacement
    assert panel._smart_auto_scroll_active
    assert panel._pending_auto_scroll is None
    loop.close()


def test_panel_error_is_propagated_and_close_joins_other_workers() -> None:
    menu, loop, _, _ = make_loop([None], content=ScreenContent.static("primary"))
    blocking = BlockingIterator()
    other = menu.add_content_panel(ScreenContent.stream(blocking), description="Other")
    assert blocking.started.wait(1)
    failed = menu.add_content_panel(
        ScreenContent.static("failed"), description="Failed"
    )
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
    menu, loop, _, _ = make_loop([None], content=ScreenContent.static("primary"))
    panel = menu.add_content_panel(ScreenContent.stream(iter(())), description="Output")
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


def test_content_replacement_waits_and_only_starts_latest_request() -> None:
    menu, loop, _, _ = make_loop([None])
    panel = menu.content_panels[0]
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

    panel.set_description("Old")
    panel.set_content(ScreenContent.stream(old_source()))
    assert old_started.wait(1)

    panel.set_description("Second")
    panel.set_content(ScreenContent.stream(second_source()))
    panel.set_description("Latest")
    panel.set_content(ScreenContent.stream(latest_source()))

    assert not second_started.is_set()
    assert not latest_started.is_set()
    old_release.set()
    assert panel._worker is not None
    assert panel._worker.join(1)

    loop._progress_panel_transitions()

    assert latest_started.wait(1)
    assert not second_started.is_set()
    assert loop.active_work is not None
    assert loop.active_work.description == "Latest"
    latest_release.set()
    loop.close()
    assert panel._worker is not None
    assert not panel._worker.is_alive()


def test_close_waits_for_cancelled_iterator_before_closing_resources() -> None:
    menu, loop, selector, _ = make_loop([None])
    panel = menu.content_panels[0]
    started = Event()
    release = Event()

    def blocked() -> Iterator[str]:
        started.set()
        release.wait()
        yield "late"

    panel.set_content(ScreenContent.stream(blocked()))
    assert started.wait(1)
    worker = panel._worker
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


def test_abandon_releases_resources_without_touching_workers() -> None:
    menu, loop, selector, _ = make_loop([None])
    work = UnstoppableWork()
    panel = menu.content_panels[0]
    panel._worker = cast(SourceWorker, work)

    loop.abandon()

    assert work.cancel_calls == 0
    assert work.join_calls == 0
    assert selector.closed
    assert loop._wakeup_reader.fileno() == -1
    assert loop._wakeup_writer.fileno() == -1


def test_dynamic_source_is_active_only_during_evaluation_and_close_joins_it() -> None:
    menu, loop, _, _ = make_loop([None])
    panel = menu.content_panels[0]
    started = Event()
    release = Event()

    def dynamic() -> str:
        started.set()
        release.wait()
        return "done"

    panel.set_description("Refreshing")
    panel.set_content(ScreenContent.dynamic(dynamic))
    assert loop.active_work is None
    loop._request_dynamic_updates()
    assert started.wait(1)
    assert loop.active_work is not None
    assert loop.active_work.description == "Refreshing"

    closer = Thread(target=loop.close)
    closer.start()
    assert closer.is_alive()
    release.set()
    closer.join(1)

    assert not closer.is_alive()
    assert panel._worker is not None
    assert not panel._worker.is_alive()


def test_responsive_layout_uses_minimums_without_resizing_the_viewport() -> None:
    rendered = Event()
    sizes: list[ContentSize] = []

    def responsive(size: ContentSize) -> str:
        sizes.append(size)
        rendered.set()
        return f"{size.width}x{size.height}"

    content = ScreenContent.responsive(
        responsive,
        min_width=40,
        min_height=20,
    )
    menu, loop, _, renderer = make_loop([None], content=content)
    panel = menu.content_panels[0]

    renderer._compose_frame(30, 15)
    assert rendered.wait(1)
    loop._drain_source_events()

    assert panel._viewport is not None
    assert (panel._viewport.width, panel._viewport.height) != (40, 20)
    assert panel._effective_size == ContentSize(40, 20)
    assert sizes == [ContentSize(40, 20)]
    first_request = panel._responsive_request_id

    renderer._compose_frame(29, 14)

    assert panel._responsive_request_id == first_request
    assert panel._viewport is not None
    assert (panel._viewport.width, panel._viewport.height) == (27, 3)
    loop.close()


def test_responsive_resize_and_manual_refresh_request_new_results() -> None:
    rendered = Event()
    sizes: list[ContentSize] = []

    def responsive(size: ContentSize) -> str:
        sizes.append(size)
        rendered.set()
        return str(len(sizes))

    content = ScreenContent.responsive(responsive, min_width=40, min_height=20)
    menu, loop, _, renderer = make_loop([None], content=content)
    panel = menu.content_panels[0]

    renderer._compose_frame(30, 15)
    assert rendered.wait(1)
    loop._drain_source_events()
    rendered.clear()

    renderer._compose_frame(52, 15)
    assert rendered.wait(1)
    loop._drain_source_events()
    assert sizes[-1].width == 50
    assert sizes[-1].height == 20
    rendered.clear()

    panel.refresh()
    assert rendered.wait(1)
    loop._drain_source_events()
    assert sizes[-1] == sizes[-2]
    loop.close()


def test_panel_sizing_reflows_responsive_content_without_restarting_workers() -> None:
    first_rendered = Event()
    second_rendered = Event()
    first_sizes: list[ContentSize] = []
    second_sizes: list[ContentSize] = []

    def first_content(size: ContentSize) -> list[str]:
        first_sizes.append(size)
        first_rendered.set()
        return ["first"] * size.height

    def second_content(size: ContentSize) -> list[str]:
        second_sizes.append(size)
        second_rendered.set()
        return ["second"] * size.height

    menu, loop, _, renderer = make_loop(
        [None], content=ScreenContent.responsive(first_content)
    )
    try:
        first = menu.content_panels[0]
        first.set_layout(max_height=3)
        second = menu.add_content_panel(
            ScreenContent.responsive(second_content, min_width=40, min_height=40),
            min_height=2,
        )
        workers = (first._worker, second._worker)
        renderer._compose_frame(30, 30)
        assert first_rendered.wait(1) and second_rendered.wait(1)
        loop._drain_source_events()
        assert first_sizes == [ContentSize(28, 3)]
        assert second_sizes == [ContentSize(40, 40)]
        first_viewport, second_viewport = first._viewport, second._viewport
        assert first_viewport is not None and second_viewport is not None
        first_request = first._responsive_request_id
        second_request = second._responsive_request_id
        first_rendered.clear()

        first.set_layout(max_height=8)
        renderer._compose_frame(30, 30)
        assert first_rendered.wait(1)
        loop._drain_source_events()
        assert first_sizes[-1] == ContentSize(28, 8)
        assert first._responsive_request_id == first_request + 1
        assert second._responsive_request_id == second_request
        assert first._viewport is first_viewport
        assert second._viewport is second_viewport
        assert second_viewport.height < 40
        assert (first._worker, second._worker) == workers

        first_rendered.clear()
        first.set_layout(weight=4)
        renderer._compose_frame(30, 30)
        assert first_rendered.wait(1)
        loop._drain_source_events()
        assert first_sizes[-1].height == first_viewport.height
        assert first_viewport.height > 8
        assert second._responsive_request_id == second_request

        first_rendered.clear()
        renderer._compose_frame(32, 34)
        assert first_rendered.wait(1)
        loop._drain_source_events()
        assert first_sizes[-1] == ContentSize(30, first_viewport.height)
        assert second_sizes == [ContentSize(40, 40)]
    finally:
        loop.close()


def test_live_layout_change_schedules_a_frame_without_content_or_input_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, loop, _, renderer = make_loop([None])
    menu._terminal_renderer = renderer
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((30, 30)),
    )
    monkeypatch.setattr(
        "tuiloom.event_loop.event_loop.get_terminal_size",
        lambda: terminal_size((30, 30)),
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", lambda _: None)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    try:
        loop.run_once(process_input=False, block=False)
        panel = menu.content_panels[0]
        assert panel._viewport is not None and panel._viewport.height > 3
        viewport = panel._viewport

        panel.set_layout(max_height=3)
        loop.run_once(process_input=False, block=False)

        assert panel._viewport is viewport
        assert viewport.height == 3
    finally:
        loop.close()


def test_responsive_results_from_obsolete_requests_are_ignored() -> None:
    content = ScreenContent.responsive(lambda size: "worker value")
    menu, loop, _, _ = make_loop([None], content=content)
    panel = menu.content_panels[0]
    panel._responsive_request_id = 2
    panel._dynamic_in_flight = True
    loop._source_events.put(
        SourceEvent(
            panel,
            panel._generation,
            "data",
            "stale",
            request_id=1,
        )
    )
    loop._source_events.put(
        SourceEvent(
            panel,
            panel._generation,
            "data",
            "current",
            request_id=2,
        )
    )

    loop._drain_source_events()

    assert panel._renderer.rendered_content.lines == ["current"]
    assert not panel._dynamic_in_flight
    loop.close()
