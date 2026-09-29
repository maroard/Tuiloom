from __future__ import annotations

from collections import deque
from contextlib import AbstractContextManager
from re import compile
from sys import stdin
from time import monotonic
from typing import TextIO, cast

from blessed import Terminal
from blessed.dec_modes import DecModeResponse, DecPrivateMode
from blessed.keyboard import Keystroke, resolve_sequence

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
# CSI/SS3 parameters and intermediates without a final byte are only prefixes.
# This detects when to wait; Blessed remains responsible for decoding keys.
_INCOMPLETE_CONTROL_SEQUENCE = compile(r"\x1b(?:\[[0-?]*[ -/]*|O[0-?]*[ -/]*)\Z")
_SEQUENCE_DELAY = 1.0


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
        self._input_buffer = ""
        # Keep reception times aligned with buffered codepoints, including keys
        # behind the event being returned and tails of later continuations.
        self._input_chunks: deque[tuple[int, float]] = deque()
        self._pending_deadline: float | None = None
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
        # Receive every currently available continuation before checking expiry.
        # inkey(timeout=0) still waits esc_delay and finalizes partial CSI/SS3;
        # keep those fragments between polls and leave decoding to Blessed.
        received = self._terminal.flushinp(timeout=0)
        if received:
            self._input_buffer += received
            self._input_chunks.append((len(received), monotonic()))
        if not self._input_buffer:
            return None
        key = self._resolve(final=False)
        incomplete = (
            self._input_buffer == "\x1b"
            or bool(_INCOMPLETE_CONTROL_SEQUENCE.fullmatch(self._input_buffer))
            or (
                self._input_buffer in self._terminal._keymap_prefixes
                and len(key) < len(self._input_buffer)
            )
        )
        if incomplete:
            now = monotonic()
            delay = (
                self._escape_delay if self._input_buffer == "\x1b" else _SEQUENCE_DELAY
            )
            self._pending_deadline = self._input_chunks[0][1] + delay
            if now < self._pending_deadline:
                return None
            key = self._resolve(final=True)
        self._input_buffer = self._input_buffer[len(key) :]
        remaining = len(key)
        while remaining:
            length, received_at = self._input_chunks.popleft()
            if length > remaining:
                self._input_chunks.appendleft((length - remaining, received_at))
                break
            remaining -= length
        self._pending_deadline = None
        return normalize_keystroke(key)

    def _resolve(self, *, final: bool) -> Keystroke:
        return resolve_sequence(
            self._input_buffer,
            self._terminal._keymap,
            self._terminal._keycodes,
            self._terminal._keymap_prefixes,
            final=final,
            dec_mode_cache=self._terminal._dec_mode_cache,
        )

    def fileno(self) -> int:
        """Return the terminal descriptor watched by the event loop."""
        return self._stream.fileno()

    def get_pending_timeout(self, now: float) -> float | None:
        """Return the remaining time before a partial sequence is finalized."""
        if self._pending_deadline is None:
            return None
        return max(0.0, self._pending_deadline - now)

    def close(self) -> None:
        """Restore terminal input settings exactly once."""
        if self._closed:
            return
        self._closed = True
        self._input_buffer = ""
        self._input_chunks.clear()
        self._pending_deadline = None
        try:
            if self._previous_focus_mode is None:
                self._terminal._dec_mode_cache.pop(self._focus_mode, None)
            else:
                self._terminal._dec_mode_cache[self._focus_mode] = (
                    self._previous_focus_mode
                )
        finally:
            self._cbreak.__exit__(None, None, None)
