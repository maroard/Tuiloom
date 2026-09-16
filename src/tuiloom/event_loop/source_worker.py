from collections.abc import Callable, Iterator
from queue import Full, Queue
from threading import Event, Lock, Thread
from typing import Literal, cast

from tuiloom.content_panel import ContentPanel
from tuiloom.event_loop.source_event import SourceEvent
from tuiloom.screen_content import ContentSize

type WorkerKind = Literal["streaming", "dynamic", "responsive"]
type WorkerSource = (
    Iterator[str]
    | Callable[[], str | list[str]]
    | Callable[[ContentSize], str | list[str]]
)


class SourceWorker:
    """Consume one synchronous content source outside the UI thread."""

    def __init__(
        self,
        panel: ContentPanel,
        generation: int,
        source: WorkerSource,
        events: Queue[SourceEvent],
        notify: Callable[[], None],
        *,
        kind: WorkerKind,
        description: str = "Content in progress",
    ) -> None:
        """Store one source and its generation-tagged output channel."""
        self.panel = panel
        self.generation = generation
        self.kind = kind
        self.source = source
        self.events = events
        self.description = description
        self._notify = notify
        self._cancelled = Event()
        self._dynamic_requested = Event()
        self._responsive_lock = Lock()
        self._responsive_request: tuple[int, ContentSize] | None = None
        self._active_request_id: int | None = None
        self._thread = Thread(target=self._run)

    def start(self) -> None:
        """Start consuming the source in a non-daemon thread."""
        self._thread.start()

    def join(self, timeout: float | None = None) -> bool:
        """Wait at most ``timeout`` seconds and report whether work stopped."""
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def is_alive(self) -> bool:
        """Return whether the source thread is still executing."""
        return self._thread.is_alive()

    def cancel(self) -> None:
        """Stop publishing and wake a waiting dynamic worker."""
        self._cancelled.set()
        self._dynamic_requested.set()
        cancel_source = getattr(self.source, "cancel", None)
        if callable(cancel_source):
            cancel_source()

    def request_dynamic_update(self) -> None:
        """Schedule one dynamic-source evaluation when supported."""
        if self.kind == "dynamic":
            self._dynamic_requested.set()

    def request_responsive_update(
        self,
        request_id: int,
        size: ContentSize,
    ) -> None:
        """Coalesce responsive work to the newest numbered request."""
        if self.kind != "responsive":
            return
        with self._responsive_lock:
            self._responsive_request = (request_id, size)
        self._dynamic_requested.set()

    def _run(self) -> None:
        """Dispatch the configured source and transport its failures."""
        try:
            if self.kind == "streaming":
                self._run_iterator(cast(Iterator[str], self.source))
            elif self.kind == "dynamic":
                self._run_dynamic(cast(Callable[[], str | list[str]], self.source))
            else:
                self._run_responsive(
                    cast(Callable[[ContentSize], str | list[str]], self.source)
                )

        except BaseException as error:
            self._publish(
                SourceEvent(
                    panel=self.panel,
                    generation=self.generation,
                    kind="error",
                    request_id=self._active_request_id,
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
                    self._publish(SourceEvent(self.panel, self.generation, "complete"))
                    return

                if self._cancelled.is_set():
                    return

                if not isinstance(chunk, str):
                    raise TypeError(
                        "Streaming content chunks must be str, "
                        f"got {type(chunk).__name__}"
                    )

                if not self._publish(
                    SourceEvent(self.panel, self.generation, "data", chunk)
                ):
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

            if not self._publish(
                SourceEvent(self.panel, self.generation, "data", content)
            ):
                return

    def _run_responsive(
        self,
        source: Callable[[ContentSize], str | list[str]],
    ) -> None:
        """Evaluate only the latest pending responsive request serially."""
        while not self._cancelled.is_set():
            self._dynamic_requested.wait()
            self._dynamic_requested.clear()
            if self._cancelled.is_set():
                return
            with self._responsive_lock:
                request = self._responsive_request
                self._responsive_request = None
            if request is None:
                continue
            request_id, size = request
            self._active_request_id = request_id
            try:
                content = source(size)
                if (
                    not isinstance(content, (str, list))
                    or isinstance(content, list)
                    and not all(isinstance(line, str) for line in content)
                ):
                    raise TypeError(
                        "Responsive content must be str or list[str], "
                        f"got {type(content).__name__}"
                    )
            except BaseException as error:
                if not self._publish(
                    SourceEvent(
                        panel=self.panel,
                        generation=self.generation,
                        kind="error",
                        request_id=request_id,
                        error=error,
                        traceback=error.__traceback__,
                    )
                ):
                    return
                self._active_request_id = None
                continue
            if not self._publish(
                SourceEvent(
                    self.panel,
                    self.generation,
                    "data",
                    content,
                    request_id=request_id,
                )
            ):
                return
            self._active_request_id = None

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
