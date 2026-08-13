import os
import selectors
import termios
import tty
from sys import stdin
from time import monotonic

from tuiloom.input_handler.input_event import InputEvent, InputEventType


class InputHandler:
    """Read and normalize non-blocking terminal input."""

    def __init__(self) -> None:
        """Configure the active terminal for non-blocking character input."""
        self.fd = stdin.fileno()
        self.original_settings = termios.tcgetattr(self.fd)

        self.selector = selectors.DefaultSelector()
        self.selector.register(stdin, selectors.EVENT_READ)

        self._input_buffer = b""
        self._escape_started_at: float | None = None
        self._escape_timeout = 0.02

        tty.setcbreak(self.fd)

    def poll(self) -> InputEvent | None:
        """Return the next available input event without blocking."""
        event = self._parse_buffer()

        if event is not None:
            return event

        events = self.selector.select(timeout=0)

        if not events:
            return None

        self._input_buffer += os.read(self.fd, 64)

        return self._parse_buffer()

    def fileno(self) -> int:
        """Return the terminal descriptor watched by the application event loop."""
        return self.fd

    def _parse_buffer(self) -> InputEvent | None:
        """Parse one normalized event from the buffered terminal bytes."""
        if not self._input_buffer:
            self._escape_started_at = None
            return None

        arrow_events: dict[bytes, InputEventType] = {
            b"A": "up",
            b"B": "down",
            b"C": "right",
            b"D": "left",
        }

        first_byte = self._input_buffer[:1]

        if first_byte in (b"\x7f", b"\x08"):
            self._input_buffer = self._input_buffer[1:]
            return InputEvent("backspace", None)

        if first_byte in (b"\n", b"\r"):
            self._input_buffer = self._input_buffer[1:]
            return InputEvent("enter", None)

        if first_byte == b"\x1b":
            if len(self._input_buffer) == 1:
                if self._escape_started_at is None:
                    self._escape_started_at = monotonic()
                    return None

                if monotonic() - self._escape_started_at < self._escape_timeout:
                    return None

                self._input_buffer = self._input_buffer[1:]
                self._escape_started_at = None

                return InputEvent("escape", None)

            self._escape_started_at = None

            if self._input_buffer[1:2] != b"[":
                self._input_buffer = self._input_buffer[1:]
                return InputEvent("escape", None)

            if len(self._input_buffer) < 3:
                return None

            event_type = arrow_events.get(self._input_buffer[2:3])

            if event_type is None:
                return None

            self._input_buffer = self._input_buffer[3:]

            return InputEvent(event_type, None)

        char = first_byte.decode()
        self._input_buffer = self._input_buffer[1:]

        return InputEvent("char", char)

    def close(self) -> None:
        """Restore the terminal settings and release the input selector."""
        termios.tcsetattr(
            self.fd,
            termios.TCSANOW,
            self.original_settings,
        )

        self.selector.close()
