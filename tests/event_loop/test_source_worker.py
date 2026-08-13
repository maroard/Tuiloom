from collections.abc import Iterator
from queue import Queue
from threading import Event

from tuiloom.event_loop.source_event import SourceEvent
from tuiloom.event_loop.source_worker import SourceWorker


def test_iterator_worker_publishes_data_and_completion() -> None:
    events: Queue[SourceEvent] = Queue(maxsize=8)
    wakeups: list[None] = []
    worker = SourceWorker(
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
    assert len(wakeups) == 3


def test_worker_transports_failure_with_traceback() -> None:
    def fail() -> Iterator[str]:
        yield "before"
        raise ValueError("broken source")

    events: Queue[SourceEvent] = Queue(maxsize=8)
    worker = SourceWorker(1, fail(), events, lambda: None)

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
    worker = SourceWorker(1, blocked(), events, lambda: None)
    worker.start()
    assert entered.wait(timeout=1)

    worker.cancel()
    release.set()
    worker.join(timeout=1)

    assert events.empty()
