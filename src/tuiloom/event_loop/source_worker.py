from collections.abc import Callable, Iterator
from queue import Full, Queue
from threading import Event, Thread

from tuiloom.event_loop.source_event import SourceEvent

type WorkerSource = Iterator[str] | Callable[[], str | list[str]]


class SourceWorker:
    """Consume one synchronous content source outside the UI thread."""

    def __init__(
        self,
        generation: int,
        source: WorkerSource,
        events: Queue[SourceEvent],
        notify: Callable[[], None],
    ) -> None:
        """Store one source and its generation-tagged output channel."""
        self.generation = generation
        self.source = source
        self.events = events
        self._notify = notify
        self._cancelled = Event()
        self._dynamic_requested = Event()
        self._thread = Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """Start consuming the source in a daemon thread."""
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        """Wait at most ``timeout`` seconds for the worker to finish."""
        self._thread.join(timeout)

    def cancel(self) -> None:
        """Stop publishing and wake a waiting dynamic worker."""
        self._cancelled.set()
        self._dynamic_requested.set()

    def request_dynamic_update(self) -> None:
        """Schedule one dynamic-source evaluation when supported."""
        if callable(self.source):
            self._dynamic_requested.set()

    def _run(self) -> None:
        """Dispatch the configured source and transport its failures."""
        try:
            if isinstance(self.source, Iterator):
                self._run_iterator(self.source)
            else:
                self._run_dynamic(self.source)

        except BaseException as error:
            self._publish(
                SourceEvent(
                    generation=self.generation,
                    kind="error",
                    error=error,
                    traceback=error.__traceback__,
                )
            )

    def _run_iterator(self, source: Iterator[str]) -> None:
        """Consume iterator chunks until completion or cancellation."""
        try:
            while not self._cancelled.is_set():
                try:
                    chunk = next(source)
                except StopIteration:
                    self._publish(SourceEvent(self.generation, "complete"))
                    return

                if self._cancelled.is_set():
                    return

                if not isinstance(chunk, str):
                    raise TypeError(
                        "Streaming content chunks must be str, "
                        f"got {type(chunk).__name__}"
                    )

                if not self._publish(SourceEvent(self.generation, "data", chunk)):
                    return

        finally:
            close = getattr(source, "close", None)
            if callable(close):
                close()

    def _run_dynamic(
        self,
        source: Callable[[], str | list[str]],
    ) -> None:
        """Evaluate a dynamic source only after explicit requests."""
        while not self._cancelled.is_set():
            self._dynamic_requested.wait()
            self._dynamic_requested.clear()

            if self._cancelled.is_set():
                return

            content = source()

            if (
                not isinstance(content, (str, list))
                or isinstance(content, list)
                and not all(isinstance(line, str) for line in content)
            ):
                raise TypeError(
                    "Dynamic content must be str or list[str], "
                    f"got {type(content).__name__}"
                )

            if not self._publish(SourceEvent(self.generation, "data", content)):
                return

    def _publish(self, event: SourceEvent) -> bool:
        """Publish one event with bounded, cancellable backpressure."""
        while not self._cancelled.is_set():
            try:
                self.events.put(event, timeout=0.05)
            except Full:
                continue

            self._notify()
            return True

        return False
