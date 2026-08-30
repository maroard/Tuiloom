from collections.abc import Callable, Iterator
from queue import Queue
from threading import Event
from typing import cast

from tuiloom import ScreenContext, TerminalApp, TerminalMenu
from tuiloom.content_panel import ContentPanel
from tuiloom.event_loop.source_event import SourceEvent
from tuiloom.event_loop.source_worker import SourceWorker
from tuiloom.output_task import OutputTaskSession


def make_panel() -> ContentPanel:
    app = TerminalApp("App")
    menu = TerminalMenu(app, ScreenContext("main", "Main"), content_source="")
    return menu.content_panels[0]


def test_iterator_worker_publishes_data_and_completion() -> None:
    events: Queue[SourceEvent] = Queue(maxsize=8)
    wakeups: list[None] = []
    worker = SourceWorker(
        panel=make_panel(),
        generation=4,
        source=iter(["first", "second"]),
        events=events,
        notify=lambda: wakeups.append(None),
    )

    worker.start()
    worker.join(timeout=1)

    received = [events.get_nowait(), events.get_nowait(), events.get_nowait()]
    assert [(event.kind, event.value) for event in received] == [
        ("data", "first"),
        ("data", "second"),
        ("complete", None),
    ]
    assert all(event.generation == 4 for event in received)
    assert all(event.panel is worker.panel for event in received)
    assert len(wakeups) == 3


def test_worker_transports_failure_with_traceback() -> None:
    def fail() -> Iterator[str]:
        yield "before"
        raise ValueError("broken source")

    events: Queue[SourceEvent] = Queue(maxsize=8)
    worker = SourceWorker(make_panel(), 1, fail(), events, lambda: None)

    worker.start()
    worker.join(timeout=1)
    events.get_nowait()
    failure = events.get_nowait()

    assert failure.kind == "error"
    assert isinstance(failure.error, ValueError)
    assert failure.traceback is not None


def test_cancelled_worker_stops_publishing_after_blocked_next_returns() -> None:
    entered = Event()
    release = Event()

    def blocked() -> Iterator[str]:
        entered.set()
        release.wait(timeout=1)
        yield "stale"

    events: Queue[SourceEvent] = Queue(maxsize=8)
    worker = SourceWorker(make_panel(), 1, blocked(), events, lambda: None)
    worker.start()
    assert entered.wait(timeout=1)

    worker.cancel()
    release.set()
    worker.join(timeout=1)

    assert events.empty()


def test_dynamic_worker_evaluates_requests_and_cancels_cleanly() -> None:
    events: Queue[SourceEvent] = Queue(maxsize=8)
    values: Iterator[str | list[str]] = iter(["first", ["second"]])
    worker = SourceWorker(make_panel(), 2, lambda: next(values), events, lambda: None)
    worker.start()
    worker.request_dynamic_update()
    first = events.get(timeout=1)
    worker.request_dynamic_update()
    second = events.get(timeout=1)
    worker.cancel()
    worker.join(timeout=1)
    assert first.value == "first"
    assert second.value == ["second"]


def test_worker_reports_invalid_iterator_and_dynamic_values() -> None:
    iterator_events: Queue[SourceEvent] = Queue(maxsize=8)
    iterator = SourceWorker(
        make_panel(),
        1,
        cast(Iterator[str], iter([3])),
        iterator_events,
        lambda: None,
    )
    iterator.start()
    iterator.join(timeout=1)
    assert isinstance(iterator_events.get_nowait().error, TypeError)

    dynamic_events: Queue[SourceEvent] = Queue(maxsize=8)
    dynamic = SourceWorker(
        make_panel(),
        1,
        cast(Callable[[], str | list[str]], lambda: 3),
        dynamic_events,
        lambda: None,
    )
    dynamic.start()
    dynamic.request_dynamic_update()
    failure = dynamic_events.get(timeout=1)
    dynamic.join(timeout=1)
    assert isinstance(failure.error, TypeError)


def test_request_dynamic_update_is_ignored_for_iterator() -> None:
    events: Queue[SourceEvent] = Queue(maxsize=8)
    worker = SourceWorker(make_panel(), 1, iter([]), events, lambda: None)
    worker.request_dynamic_update()


def test_source_worker_exposes_non_daemon_background_work_contract() -> None:
    release = Event()

    def blocked() -> Iterator[str]:
        release.wait()
        yield "done"

    worker = SourceWorker(
        make_panel(),
        1,
        blocked(),
        Queue(maxsize=8),
        lambda: None,
        description="Generating",
    )

    worker.start()

    assert worker.description == "Generating"
    assert worker.is_alive()
    assert not worker._thread.daemon

    worker.cancel()
    release.set()
    assert worker.join(timeout=1)
    assert not worker.is_alive()


def test_cancelling_output_view_wakes_source_worker_without_finishing_task() -> None:
    session = OutputTaskSession()
    worker = SourceWorker(
        make_panel(),
        1,
        session.iter_output(),
        Queue(maxsize=8),
        lambda: None,
    )
    worker.start()

    worker.cancel()
    stopped_without_outcome = worker.join(timeout=0.1)
    session.finish_success(None)
    worker.join(timeout=1)

    assert stopped_without_outcome
