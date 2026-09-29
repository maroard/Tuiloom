from __future__ import annotations

from contextlib import AbstractContextManager
from sys import stdin
from typing import TextIO, cast

from blessed import Terminal
from blessed.dec_modes import DecModeResponse, DecPrivateMode
from blessed.keyboard import Keystroke

from tuiloom.input_handler.input_event import InputEvent
from tuiloom.key_binding import KeyBinding

_LEGACY_NAMES: dict[str, tuple[str, bool]] = {
    "SUP": ("up", True),
    "SDOWN": ("down", True),
    "SLEFT": ("left", True),
    "SRIGHT": ("right", True),
    "STAB": ("tab", True),
    "BTAB": ("tab", True),
}
_SPECIAL_NAMES = {
    "ESCAPE": "escape",
    "ENTER": "enter",
    "RETURN": "enter",
    "BACKSPACE": "backspace",
    "TAB": "tab",
    "UP": "up",
    "DOWN": "down",
    "LEFT": "left",
    "RIGHT": "right",
}


def normalize_keystroke(key: Keystroke) -> InputEvent:
    """Convert a Blessed keystroke into a Tuiloom input event.

    Unknown sequences remain consumable bindings, so malformed or unsupported
    terminal input can never block later events in the input buffer.
    """
    name = key.name
    if name in {"FOCUS_IN", "FOCUS_OUT"}:
        return InputEvent(None, terminal_focus=name == "FOCUS_IN")
    raw_value = getattr(key, "value", str(key))
    value = raw_value if isinstance(raw_value, str) else str(key)

    if name is None:
        text = str(key)
        if not text:
            return InputEvent(None)
        if len(text) == 1:
            return InputEvent(KeyBinding(text), text)
        return InputEvent(None, text)

    raw_name = name.removeprefix("KEY_")
    legacy = _LEGACY_NAMES.get(raw_name)
    if legacy is not None:
        legacy_binding, shifted = legacy
        return InputEvent(KeyBinding(legacy_binding, shift=shifted))

    parts = raw_name.split("_")
    ctrl = False
    alt = False
    shift = False
    while parts and parts[0] in {"CTRL", "ALT", "SHIFT"}:
        modifier = parts.pop(0)
        ctrl = ctrl or modifier == "CTRL"
        alt = alt or modifier == "ALT"
        shift = shift or modifier == "SHIFT"

    base_name = "_".join(parts)
    resolved_binding: str | None = _SPECIAL_NAMES.get(base_name)
    if resolved_binding is None:
        if value and len(value) == 1:
            resolved_binding = value
        else:
            resolved_binding = base_name.lower() or raw_name.lower()

    event_text: str | None = value if value and not (ctrl or alt) else None
    return InputEvent(
        KeyBinding(resolved_binding, ctrl=ctrl, alt=alt, shift=shift),
        event_text,
    )


class InputHandler:
    """Read decoded Unicode and special-key events through Blessed."""

    def __init__(
        self,
        terminal: Terminal | None = None,
        stream: TextIO = stdin,
        *,
        escape_delay: float = 0.02,
    ) -> None:
        """Enter cbreak mode for the interactive input stream."""
        self._terminal = terminal if terminal is not None else Terminal()
        self._stream = stream
        self._escape_delay = escape_delay
        # TerminalApp owns mode 1004 via save/set/restore, without querying it.
        # Blessed >=1.48,<2 gates its native focus decoder on this private cache.
        # Prime only that entry: focus reports must remain atomic even when
        # NO_COLOR disables Blessed's queries. Avoid a second input parser and
        # responses arriving after a negotiation timeout becoming user input.
        self._focus_mode = int(DecPrivateMode.FOCUS_IN_OUT_EVENTS)
        self._previous_focus_mode = self._terminal._dec_mode_cache.get(self._focus_mode)
        self._cbreak = cast(AbstractContextManager[object], self._terminal.cbreak())
        self._cbreak.__enter__()
        self._terminal._dec_mode_cache[self._focus_mode] = DecModeResponse.SET
        self._closed = False

    def poll(self) -> InputEvent | None:
        """Return one decoded event immediately, or ``None`` when idle."""
        key = self._terminal.inkey(timeout=0, esc_delay=self._escape_delay)
        if not key:
            return None
        return normalize_keystroke(key)

    def fileno(self) -> int:
        """Return the terminal descriptor watched by the event loop."""
        return self._stream.fileno()

    def get_pending_timeout(self, now: float) -> float | None:
        """Return no external deadline because Blessed owns Escape timing."""
        return None

    def close(self) -> None:
        """Restore terminal input settings exactly once."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._previous_focus_mode is None:
                self._terminal._dec_mode_cache.pop(self._focus_mode, None)
            else:
                self._terminal._dec_mode_cache[self._focus_mode] = (
                    self._previous_focus_mode
                )
        finally:
            self._cbreak.__exit__(None, None, None)
