from collections.abc import Callable, Iterator
from dataclasses import dataclass
from threading import Condition, Thread

from tuiloom.output_capture import OutputCapture


@dataclass(frozen=True, slots=True)
class OutputTaskOutcome:
    """Store the return value or exception produced by an output task."""

    result: object = None
    error: Exception | None = None


class _OutputView(Iterator[str]):
    """Read one replayable session stream with independent cancellation."""

    def __init__(self, session: "OutputTaskSession") -> None:
        self._session = session
        self._cursor = 0
        self._cancelled = False

    def __next__(self) -> str:
        session = self._session
        with session._condition:
            while (
                self._cursor >= len(session._chunks)
                and session._outcome is None
                and not session._cancelled
                and not self._cancelled
            ):
                session._condition.wait()

            if self._cancelled:
                raise StopIteration
            if self._cursor < len(session._chunks):
                chunk = session._chunks[self._cursor]
                self._cursor += 1
                return chunk
            raise StopIteration

    def cancel(self) -> None:
        """Stop this view and wake its possibly waiting consumer."""
        with self._session._condition:
            self._cancelled = True
            self._session._condition.notify_all()

    def close(self) -> None:
        """Support the close convention used by iterator consumers."""
        self.cancel()


class OutputTaskSession:
    """Accumulate replayable output and the eventual task outcome."""

    def __init__(self, description: str = "Task in progress") -> None:
        """Create an unfinished session with no captured output."""
        self.description = description
        self._chunks: list[str] = []
        self._outcome: OutputTaskOutcome | None = None
        self._condition = Condition()
        self._worker: Thread | None = None
        self._cancelled = False

    @property
    def outcome(self) -> OutputTaskOutcome | None:
        """Return the completed outcome, or ``None`` while still running."""
        with self._condition:
            return self._outcome

    def append_output(self, text: str) -> None:
        """Append one output fragment and wake every attached menu view."""
        if not text:
            return

        with self._condition:
            if self._outcome is not None or self._cancelled:
                return
            self._chunks.append(text)
            self._condition.notify_all()

    def start(
        self,
        action: Callable[[], object],
        capture: OutputCapture,
        publish_outcome: Callable[["OutputTaskSession"], object],
    ) -> None:
        """Start one captured action in a non-daemon worker thread."""
        with self._condition:
            if self._worker is not None:
                raise RuntimeError("Output task session is already started")
            self._worker = Thread(
                target=self._run,
                args=(action, capture, publish_outcome),
            )
            worker = self._worker

        worker.start()

    def join(self, timeout: float | None = None) -> bool:
        """Wait at most ``timeout`` seconds and report whether the worker stopped."""
        with self._condition:
            worker = self._worker

        if worker is None:
            raise RuntimeError("Output task session has not been started")

        worker.join(timeout)
        return not worker.is_alive()

    def is_alive(self) -> bool:
        """Return whether the action thread is still executing."""
        with self._condition:
            worker = self._worker
        return worker is not None and worker.is_alive()

    def cancel(self) -> None:
        """Discard future output and wake attached views cooperatively."""
        with self._condition:
            self._cancelled = True
            self._condition.notify_all()

    def iter_output(self) -> Iterator[str]:
        """Return a replayable, independently cancellable output view."""
        return _OutputView(self)

    def finish_success(self, result: object) -> None:
        """Finish successfully and wake every attached output view."""
        self._finish(OutputTaskOutcome(result=result))

    def finish_error(self, error: Exception) -> None:
        """Finish with ``error`` and wake every attached output view."""
        self._finish(OutputTaskOutcome(error=error))

    def _finish(self, outcome: OutputTaskOutcome) -> None:
        """Store exactly one terminal outcome."""
        with self._condition:
            if self._outcome is not None:
                raise RuntimeError("Output task session is already complete")
            self._outcome = outcome
            self._condition.notify_all()

    def _run(
        self,
        action: Callable[[], object],
        capture: OutputCapture,
        publish_outcome: Callable[["OutputTaskSession"], object],
    ) -> None:
        """Execute the action, capture its output, and publish its outcome."""
        try:
            try:
                with capture.route_background_output(self.append_output):
                    result = action()
            except Exception as error:
                self.finish_error(error)
            except BaseException as error:
                normalized_error = RuntimeError(
                    f"Output task stopped with {type(error).__name__}: {error}"
                )
                normalized_error.__cause__ = error
                self.finish_error(normalized_error)
            else:
                self.finish_success(result)
        finally:
            publish_outcome(self)
