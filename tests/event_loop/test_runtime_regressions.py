from __future__ import annotations

from collections.abc import Iterator
from socket import socket
from threading import Event
from typing import Literal, cast

import pytest

from tuiloom import ContentSize, MenuDisplay, ScreenContent, TerminalMenu
from tuiloom.event_loop.source_event import SourceEvent
from tuiloom.event_loop.source_worker import SourceWorker
from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.task_exit import TaskExitState

from .test_event_loop import BlockingIterator, make_loop


class ScheduledWork:
    def __init__(self) -> None:
        self.dynamic_requests = 0
        self.responsive_requests: list[tuple[int, ContentSize]] = []
        self.cancel_calls = 0
        self.join_calls = 0

    def request_dynamic_update(self) -> None:
        self.dynamic_requests += 1

    def request_responsive_update(self, request_id: int, size: ContentSize) -> None:
        self.responsive_requests.append((request_id, size))

    def is_alive(self) -> bool:
        return True

    def cancel(self) -> None:
        self.cancel_calls += 1

    def join(self, timeout: float | None = None) -> bool:
        self.join_calls += 1
        return True


def wait_to_exit(menu: TerminalMenu, *, stacked: bool) -> TerminalMenu:
    waiting_menu = (
        TerminalMenu(menu.app, MenuDisplay("child", "Child")) if stacked else menu
    )
    if stacked:
        menu.app._menu_stack = [menu, waiting_menu]
    waiting_menu._task_exit = TaskExitState(
        mode="waiting",
        selected_index=0,
        previous_focus=None,
        previous_selected_index=0,
        wait_started_at=0,
        visible_panels=menu.content_panels,
    )
    return waiting_menu


@pytest.mark.parametrize("responsive", [False, True])
@pytest.mark.parametrize("removed", [False, True])
def test_replaced_callback_stays_active_until_its_worker_terminates(
    responsive: bool, removed: bool
) -> None:
    started, release = Event(), Event()

    def produce() -> str:
        started.set()
        release.wait()
        return "obsolete"

    content = (
        ScreenContent.responsive(lambda size: produce())
        if responsive
        else ScreenContent.dynamic(produce)
    )
    menu, loop, _, _ = make_loop([None], content=content)
    panel = menu.content_panels[0]
    old_worker = panel._runtime.worker
    assert old_worker is not None
    try:
        if responsive:
            loop.update_content_panel_size(panel, ContentSize(20, 6))
        else:
            loop._request_dynamic_updates()
        assert started.wait(1)
        old_generation = panel._runtime.generation

        panel.set_content(ScreenContent.static("replacement"))
        if removed:
            panel.remove()
        loop._source_events.put(SourceEvent(panel, old_generation, "data", "old"))
        loop._drain_source_events()

        assert panel._runtime.dynamic_in_flight
        assert loop.active_panels == (panel,)
        assert loop.active_work is old_worker
        release.set()
        assert old_worker.join(1)
        loop._progress_panel_transitions()
        assert not loop.active_panels
        if removed:
            assert loop.retiring_panels == ()
        else:
            assert panel._runtime.renderer.rendered_content.lines == ["replacement"]
    finally:
        release.set()
        loop.close()


@pytest.mark.parametrize("stacked", [False, True])
@pytest.mark.parametrize("responsive", [False, True])
def test_wait_and_quit_suspends_periodic_refreshes_and_their_deadlines(
    stacked: bool, responsive: bool
) -> None:
    menu, loop, _, _ = make_loop([None])
    panel = menu.content_panels[0]
    content = (
        ScreenContent.responsive(lambda size: "value", refresh_mode="continuous")
        if responsive
        else ScreenContent.dynamic(lambda: "value")
    )
    panel._content = content
    panel._runtime.renderer = ContentRenderer(content)
    panel._runtime.effective_size = ContentSize(20, 6)
    work = ScheduledWork()
    panel._runtime.worker = cast(SourceWorker, work)
    waiting_menu = wait_to_exit(menu, stacked=stacked)
    loop._dirty = False
    loop._next_state_check_at = 10
    try:
        loop._request_dynamic_updates()

        assert work.dynamic_requests == 0
        assert work.responsive_requests == []
        assert not panel._runtime.dynamic_in_flight
        assert loop._get_wait_timeout() == 10

        waiting_menu._cancel_task_exit()
        loop._request_dynamic_updates()
        assert work.dynamic_requests == int(not responsive)
        assert len(work.responsive_requests) == int(responsive)
        assert panel._runtime.dynamic_in_flight
    finally:
        loop.close()


@pytest.mark.parametrize("trigger", ["layout", "manual", "direct"])
@pytest.mark.parametrize("stacked", [False, True])
def test_wait_and_quit_defers_responsive_refresh_until_cancellation(
    trigger: Literal["layout", "manual", "direct"], stacked: bool
) -> None:
    menu, loop, _, _ = make_loop([None])
    panel = menu.content_panels[0]
    panel._content = ScreenContent.responsive(lambda size: "value")
    panel._runtime.renderer = ContentRenderer(panel._content)
    size = ContentSize(20, 6)
    panel._runtime.effective_size = size
    work = ScheduledWork()
    panel._runtime.worker = cast(SourceWorker, work)
    waiting_menu = wait_to_exit(menu, stacked=stacked)
    try:
        if trigger == "layout":
            size = ContentSize(30, 8)
            loop.update_content_panel_size(panel, size)
        elif trigger == "manual":
            loop.refresh_content_panel(panel)
        else:
            loop._request_responsive_update(panel, size)

        assert work.responsive_requests == []
        assert panel._runtime.responsive_request_id == 0
        assert panel._runtime.responsive_refresh_pending
        assert not panel._runtime.dynamic_in_flight

        waiting_menu._cancel_task_exit()
        loop._request_dynamic_updates()
        assert work.responsive_requests == [(1, size)]
        assert not panel._runtime.responsive_refresh_pending
    finally:
        loop.close()


def test_wait_and_quit_still_drains_existing_stream_results() -> None:
    published, release = Event(), Event()

    def source() -> Iterator[str]:
        yield "arrived\n"
        published.set()
        release.wait()

    menu, loop, _, _ = make_loop([None], content=ScreenContent.stream(source()))
    panel = menu.content_panels[0]
    try:
        assert published.wait(1)
        wait_to_exit(menu, stacked=False)

        loop.run_once(process_input=False, render=False, block=False)

        assert panel._runtime.renderer.rendered_content.lines == ["arrived"]
        assert loop.active_panels == (panel,)
    finally:
        release.set()
        loop.close()


def test_close_finishes_other_cleanup_after_a_cancel_hook_raises() -> None:
    menu, loop, selector, _ = make_loop([None])
    calls: list[str] = []

    class FailingWork(ScheduledWork):
        def cancel(self) -> None:
            calls.append("first cancel")
            raise ValueError("cancel failed")

        def join(self, timeout: float | None = None) -> bool:
            calls.append("first join")
            return True

    first = FailingWork()
    second = ScheduledWork()
    menu.content_panels[0]._runtime.worker = cast(SourceWorker, first)
    other = menu.add_content_panel(ScreenContent.static("other"))
    other._runtime.worker = cast(SourceWorker, second)

    with pytest.raises(ValueError, match="cancel failed"):
        loop.close()

    assert calls == ["first cancel", "first join"]
    assert (second.cancel_calls, second.join_calls) == (1, 1)
    assert selector.closed
    assert loop._wakeup_reader.fileno() == -1
    assert loop._wakeup_writer.fileno() == -1
    loop.close()
    assert (second.cancel_calls, second.join_calls) == (1, 1)


def test_close_preserves_all_failures_and_attempts_each_resource() -> None:
    menu, loop, selector, _ = make_loop([None])
    calls: list[str] = []
    original_reader, original_writer = loop._wakeup_reader, loop._wakeup_writer
    errors = [ValueError("cancel"), KeyboardInterrupt("join"), OSError("reader")]

    class FailingWork(ScheduledWork):
        def cancel(self) -> None:
            calls.append("cancel")
            raise errors[0]

        def join(self, timeout: float | None = None) -> bool:
            calls.append("join")
            raise errors[1]

    class Resource:
        def __init__(self, label: str, error: BaseException | None = None) -> None:
            self.label = label
            self.error = error

        def close(self) -> None:
            calls.append(self.label)
            if self.error is not None:
                raise self.error

    menu.content_panels[0]._runtime.worker = cast(SourceWorker, FailingWork())
    loop._wakeup_reader = cast(socket, Resource("reader", errors[2]))
    loop._wakeup_writer = cast(socket, Resource("writer"))
    try:
        with pytest.raises(BaseExceptionGroup) as raised:
            loop.close()

        assert calls == ["cancel", "join", "reader", "writer"]
        assert selector.closed
        assert list(raised.value.exceptions) == errors
        loop.close()
        assert calls == ["cancel", "join", "reader", "writer"]
    finally:
        original_reader.close()
        original_writer.close()


def test_removed_worker_is_tracked_even_when_its_cancel_hook_raises() -> None:
    menu, loop, _, _ = make_loop([None])
    panel = menu.add_content_panel(ScreenContent.static("Content"))

    class FailingCancellation(ScheduledWork):
        def cancel(self) -> None:
            super().cancel()
            raise RuntimeError("cancel failed")

    work = FailingCancellation()
    panel._runtime.worker = cast(SourceWorker, work)
    try:
        with pytest.raises(RuntimeError, match="cancel failed"):
            panel.remove()
        assert panel in loop.retiring_panels
        assert panel in loop.active_panels
    finally:
        with pytest.raises(RuntimeError, match="cancel failed"):
            loop.close()
    assert work.join_calls == 1


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_close_releases_retired_stream_claims_after_joining(
    monkeypatch: pytest.MonkeyPatch, cleanup_fails: bool
) -> None:
    source = BlockingIterator()
    menu, loop, selector, _ = make_loop([None], content=ScreenContent.stream(source))
    panel = menu.content_panels[0]
    worker = panel._runtime.worker
    assert worker is not None
    assert source.started.wait(1)
    panel.remove()

    def fail_close() -> None:
        raise OSError("selector cleanup failed")

    if cleanup_fails:
        monkeypatch.setattr(selector, "close", fail_close)
    try:
        if cleanup_fails:
            with pytest.raises(OSError, match="selector cleanup failed"):
                loop.close()
        else:
            loop.close()

        assert not worker.is_alive()
        assert len(menu.app._stream_owners) == 0
        assert loop.retiring_panels == ()
        assert not panel._runtime.retiring
    finally:
        source.release.set()
        worker.join(1)
        loop.close()
