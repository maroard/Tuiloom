import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import RLock, get_ident
from typing import TextIO, cast

type OutputWriter = Callable[[str], object]


class _RoutedTextStream:
    """Forward UI writes and route active background writes to a callback."""

    def __init__(self, capture: "OutputCapture", fallback: TextIO) -> None:
        self._capture = capture
        self._fallback = fallback

    @property
    def encoding(self) -> str | None:
        """Expose the fallback stream encoding."""
        return self._fallback.encoding

    @property
    def errors(self) -> str | None:
        """Expose the fallback stream error policy."""
        return self._fallback.errors

    def write(self, text: str) -> int:
        """Route one text fragment or write it to the original stream."""
        writer = self._capture._background_writer()

        if writer is None:
            return self._fallback.write(text)

        writer(text)
        return len(text)

    def flush(self) -> None:
        """Flush the original stream when output is not being captured."""
        if self._capture._background_writer() is None:
            self._fallback.flush()

    def isatty(self) -> bool:
        """Present captured output as interactive progress-capable output."""
        if self._capture._background_writer() is not None:
            return True
        return self._fallback.isatty()

    def fileno(self) -> int:
        """Expose the original stream file descriptor."""
        return self._fallback.fileno()

    def writable(self) -> bool:
        """Report that the routed text stream accepts writes."""
        return True


class OutputCapture:
    """Route background text output while preserving the UI stream."""

    def __init__(self) -> None:
        """Create an inactive application-scoped output router."""
        self._owner_thread_id: int | None = None
        self._writer: OutputWriter | None = None
        self._lock = RLock()
        self._installed = False

    @contextmanager
    def install(self) -> Iterator[None]:
        """Install routed stdout and stderr until the context exits."""
        with self._lock:
            if self._installed:
                raise RuntimeError("Output capture is already installed")

            stdout = sys.stdout
            stderr = sys.stderr
            self._owner_thread_id = get_ident()
            self._installed = True

        sys.stdout = cast(TextIO, _RoutedTextStream(self, stdout))
        sys.stderr = cast(TextIO, _RoutedTextStream(self, stderr))

        try:
            yield
        finally:
            sys.stdout = stdout
            sys.stderr = stderr
            with self._lock:
                self._writer = None
                self._owner_thread_id = None
                self._installed = False

    @contextmanager
    def route_background_output(
        self,
        writer: OutputWriter,
    ) -> Iterator[None]:
        """Route non-UI thread writes to ``writer`` for one task."""
        with self._lock:
            if not self._installed:
                raise RuntimeError("Output capture is not installed")
            if self._writer is not None:
                raise RuntimeError("Another output task is already running")
            self._writer = writer

        try:
            yield
        finally:
            with self._lock:
                if self._writer is writer:
                    self._writer = None

    def _background_writer(self) -> OutputWriter | None:
        """Return the active writer outside the application UI thread."""
        with self._lock:
            if get_ident() == self._owner_thread_id:
                return None
            return self._writer
