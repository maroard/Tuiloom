from collections.abc import Callable, Iterator
from dataclasses import dataclass
from threading import Condition, Thread

from tuiloom.output_capture import OutputCapture


@dataclass(frozen=True, slots=True)
class OutputTaskOutcome:
    """Store the return value or exception produced by an output task."""

    result: object = None
    error: Exception | None = None


class OutputTaskSession:
    """Accumulate replayable output and the eventual task outcome."""

    def __init__(self) -> None:
        """Create an unfinished session with no captured output."""
        self._chunks: list[str] = []
        self._outcome: OutputTaskOutcome | None = None
        self._condition = Condition()
        self._worker: Thread | None = None

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
            if self._outcome is not None:
                return
            self._chunks.append(text)
            self._condition.notify_all()

    def start(
        self,
        action: Callable[[], object],
        capture: OutputCapture,
        publish_outcome: Callable[["OutputTaskSession"], object],
    ) -> None:
        """Start one captured action in a daemon worker thread."""
        with self._condition:
            if self._worker is not None:
                raise RuntimeError("Output task session is already started")
            self._worker = Thread(
                target=self._run,
                args=(action, capture, publish_outcome),
                daemon=True,
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

    def iter_output(self) -> Iterator[str]:
        """Yield all stored output, then wait for new fragments until done."""
        cursor = 0

        while True:
            with self._condition:
                while cursor >= len(self._chunks) and self._outcome is None:
                    self._condition.wait()
                chunks = self._chunks[cursor:]
                cursor += len(chunks)
                complete = self._outcome is not None

            yield from chunks

            if complete:
                return

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
