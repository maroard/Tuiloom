from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast

import pytest
from blessed import Terminal
from blessed.dec_modes import DecModeResponse, DecPrivateMode
from blessed.keyboard import Keystroke

from tuiloom import KeyBinding
from tuiloom.input_handler.input_handler import InputHandler, normalize_keystroke


def stroke(
    ucs: str,
    *,
    name: str | None = None,
    code: int | None = None,
) -> Keystroke:
    return Keystroke(ucs=ucs, name=name, code=code)


def test_normalizes_unicode_and_multi_character_paste() -> None:
    unicode_event = normalize_keystroke(stroke("界"))
    paste_event = normalize_keystroke(stroke("café 👨‍👩‍👧"))
    assert unicode_event.binding == KeyBinding("界")
    assert unicode_event.text == "界"
    assert paste_event.binding is None
    assert paste_event.text == "café 👨‍👩‍👧"


def test_normalizes_empty_and_common_special_keys() -> None:
    assert normalize_keystroke(stroke("")).binding is None
    cases = {
        "KEY_UP": KeyBinding("up"),
        "KEY_DOWN": KeyBinding("down"),
        "KEY_LEFT": KeyBinding("left"),
        "KEY_RIGHT": KeyBinding("right"),
        "KEY_ENTER": KeyBinding("enter"),
        "KEY_ESCAPE": KeyBinding("escape"),
        "KEY_BACKSPACE": KeyBinding("backspace"),
        "KEY_TAB": KeyBinding("tab"),
    }
    for name, expected in cases.items():
        event = normalize_keystroke(stroke("\x1b", name=name, code=1))
        assert event.binding == expected


def test_normalizes_modifiers_legacy_shift_and_unknown_sequences() -> None:
    ctrl_alt = normalize_keystroke(stroke("\x18", name="KEY_CTRL_ALT_X"))
    shifted = normalize_keystroke(stroke("\x1b[1;2A", name="KEY_SUP"))
    unknown = normalize_keystroke(stroke("\x1b[99~", name="KEY_MYSTERY"))
    assert ctrl_alt.binding == KeyBinding("x", ctrl=True, alt=True)
    assert ctrl_alt.text is None
    assert shifted.binding == KeyBinding("up", shift=True)
    assert unknown.binding == KeyBinding("mystery")
    assert unknown.text is None


def test_modifier_special_key_and_synthesized_printable_name() -> None:
    special = normalize_keystroke(stroke("\x1b[1;6D", name="KEY_CTRL_SHIFT_LEFT"))
    printable = normalize_keystroke(stroke("a", name="KEY_A"))
    assert special.binding == KeyBinding("left", ctrl=True, shift=True)
    assert printable.binding == KeyBinding("a")
    assert printable.text == "a"


@pytest.mark.parametrize(
    ("direction", "final"),
    [("up", "A"), ("down", "B"), ("right", "C"), ("left", "D")],
)
def test_decodes_ctrl_arrows(direction: str, final: str) -> None:
    terminal = Terminal()
    sequence = f"\x1b[1;5{final}"
    from blessed.keyboard import resolve_sequence

    key = resolve_sequence(
        sequence,
        terminal._keymap,
        terminal._keycodes,
        terminal._keymap_prefixes,
        final=True,
        dec_mode_cache=terminal._dec_mode_cache,
    )
    assert normalize_keystroke(key).binding == KeyBinding(direction, ctrl=True)


@pytest.mark.parametrize("gained", [False, True])
def test_terminal_focus_notifications_are_not_keyboard_commands(gained: bool) -> None:
    event = normalize_keystroke(
        stroke(
            "\x1b[I" if gained else "\x1b[O", name="FOCUS_IN" if gained else "FOCUS_OUT"
        )
    )
    assert event.binding is None
    assert event.text is None
    assert event.terminal_focus is gained


class _BreakContext:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    def __enter__(self) -> None:
        self.entered = True

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self.exited = True


class _FakeTerminal:
    def __init__(self, keys: Iterator[Keystroke]) -> None:
        self.keys = keys
        self.context = _BreakContext()
        self._dec_mode_cache: dict[int, int] = {}
        self.calls: list[float] = []
        decoder = Terminal()
        self._keymap = decoder._keymap
        self._keycodes = decoder._keycodes
        self._keymap_prefixes = decoder._keymap_prefixes

    def cbreak(self) -> _BreakContext:
        return self.context

    def flushinp(self, timeout: float) -> str:
        self.calls.append(timeout)
        return str(next(self.keys, Keystroke()))


class _FakeStream:
    def fileno(self) -> int:
        return 42


@pytest.mark.parametrize("previous", [None, DecModeResponse.SET, DecModeResponse.RESET])
def test_input_handler_polls_without_blocking_and_restores_once(
    previous: int | None,
) -> None:
    terminal = _FakeTerminal(iter([stroke("é"), stroke("")]))
    if previous is not None:
        terminal._dec_mode_cache[DecPrivateMode.FOCUS_IN_OUT_EVENTS] = previous
    stream = _FakeStream()
    handler = InputHandler(
        terminal=cast(object, terminal),  # type: ignore[arg-type]
        stream=cast(object, stream),  # type: ignore[arg-type]
        escape_delay=0.03,
    )
    assert terminal.context.entered
    assert (
        terminal._dec_mode_cache[DecPrivateMode.FOCUS_IN_OUT_EVENTS]
        == DecModeResponse.SET
    )
    assert handler.poll() is not None
    assert handler.poll() is None
    assert terminal.calls == [0, 0]
    assert handler.fileno() == 42
    assert handler.get_pending_timeout(1.0) is None
    handler.close()
    handler.close()
    assert terminal.context.exited
    assert terminal._dec_mode_cache.get(DecPrivateMode.FOCUS_IN_OUT_EVENTS) == previous


def test_blessed_decodes_focus_unicode_navigation_and_escape_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    clock = _Clock()
    monkeypatch.setattr(
        "tuiloom.input_handler.input_handler.monotonic", clock, raising=False
    )
    terminal = Terminal()
    handler = InputHandler(terminal=terminal)
    try:
        terminal.ungetch("\x1b[O\x1b[Ié\x1b[A\x1b")
        lost = handler.poll()
        gained = handler.poll()
        text = handler.poll()
        up = handler.poll()
        assert handler.poll() is None
        clock.now += 0.02
        escape = handler.poll()
        assert lost is not None and lost.terminal_focus is False
        assert gained is not None and gained.terminal_focus is True
        assert text is not None and text.text == "é"
        assert up is not None and up.binding == KeyBinding("up")
        assert escape is not None and escape.binding == KeyBinding("escape")
        assert handler.poll() is None
    finally:
        handler.close()
    assert DecPrivateMode.FOCUS_IN_OUT_EVENTS not in terminal._dec_mode_cache


@dataclass
class _Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def progressive_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[InputHandler, Terminal, _Clock]]:
    clock = _Clock()
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(
        "tuiloom.input_handler.input_handler.monotonic", clock, raising=False
    )
    terminal = Terminal()
    handler = InputHandler(terminal=terminal)
    try:
        yield handler, terminal, clock
    finally:
        handler.close()


@pytest.mark.parametrize("report,gained", [("I", True), ("O", False)])
def test_fragmented_focus_report_survives_escape_delay(
    progressive_handler: tuple[InputHandler, Terminal, _Clock],
    report: str,
    gained: bool,
) -> None:
    handler, terminal, clock = progressive_handler
    terminal.ungetch("\x1b[")
    assert handler.poll() is None
    assert handler.get_pending_timeout(clock.now) == pytest.approx(1.0)
    clock.now = 0.05
    terminal.ungetch(report)
    event = handler.poll()
    assert event is not None and event.terminal_focus is gained
    assert event.binding is None and event.text is None
    assert handler.poll() is None
    assert handler.get_pending_timeout(clock.now) is None


def test_fragmented_focus_reports_preserve_surrounding_event_order(
    progressive_handler: tuple[InputHandler, Terminal, _Clock],
) -> None:
    handler, terminal, clock = progressive_handler
    terminal.ungetch("é\x1b[O\x1b[")
    before = handler.poll()
    lost = handler.poll()
    assert before is not None and before.text == "é"
    assert lost is not None and lost.terminal_focus is False
    assert handler.poll() is None
    clock.now = 0.05
    terminal.ungetch("I界\x1b[A")
    gained = handler.poll()
    after = handler.poll()
    up = handler.poll()
    assert gained is not None and gained.terminal_focus is True
    assert gained.binding is None and gained.text is None
    assert after is not None and after.text == "界"
    assert up is not None and up.binding == KeyBinding("up")
    assert handler.poll() is None


def test_bare_escape_waits_only_twenty_milliseconds(
    progressive_handler: tuple[InputHandler, Terminal, _Clock],
) -> None:
    handler, terminal, clock = progressive_handler
    terminal.ungetch("\x1b")
    assert handler.poll() is None
    assert handler.get_pending_timeout(clock.now) == pytest.approx(0.02)
    clock.now = 0.019
    assert handler.poll() is None
    assert handler.get_pending_timeout(clock.now) == pytest.approx(0.001)
    clock.now = 0.02
    assert handler.get_pending_timeout(clock.now) == 0
    escape = handler.poll()
    assert escape is not None and escape.binding == KeyBinding("escape")
    assert handler.poll() is None
    assert handler.get_pending_timeout(clock.now) is None


@pytest.mark.parametrize(
    "prefix,continuation,binding",
    [
        ("\x1b[1;", "6D", KeyBinding("left", ctrl=True, shift=True)),
        ("\x1bO", "2P", KeyBinding("f1", shift=True)),
    ],
)
def test_fragmented_navigation_uses_blessed_decoder(
    progressive_handler: tuple[InputHandler, Terminal, _Clock],
    prefix: str,
    continuation: str,
    binding: KeyBinding,
) -> None:
    handler, terminal, clock = progressive_handler
    terminal.ungetch(prefix)
    assert handler.poll() is None
    clock.now = 0.05
    terminal.ungetch(continuation)
    event = handler.poll()
    assert event is not None and event.binding == binding
    assert handler.poll() is None


def test_sequence_progress_extends_escape_to_bounded_sequence_deadline(
    progressive_handler: tuple[InputHandler, Terminal, _Clock],
) -> None:
    handler, terminal, clock = progressive_handler
    terminal.ungetch("\x1b")
    assert handler.poll() is None
    clock.now = 0.01
    terminal.ungetch("[")
    assert handler.poll() is None
    assert handler.get_pending_timeout(clock.now) == pytest.approx(0.99)
    clock.now = 0.9
    terminal.ungetch("1;")
    assert handler.poll() is None
    assert handler.get_pending_timeout(clock.now) == pytest.approx(0.1)
    clock.now = 1.5
    assert handler.get_pending_timeout(clock.now) == 0
    expired = handler.poll()
    assert expired is not None
    terminal.ungetch("é")
    remaining = []
    while (event := handler.poll()) is not None:
        remaining.append(event)
    assert remaining[-1].text == "é"
    assert handler.get_pending_timeout(clock.now) is None


def test_available_continuation_is_read_before_sequence_expiry(
    progressive_handler: tuple[InputHandler, Terminal, _Clock],
) -> None:
    handler, terminal, clock = progressive_handler
    terminal.ungetch("\x1b[")
    assert handler.poll() is None
    clock.now = 1.5
    terminal.ungetch("Ié")
    gained = handler.poll()
    text = handler.poll()
    assert gained is not None and gained.terminal_focus is True
    assert gained.binding is None and gained.text is None
    assert text is not None and text.text == "é"
    assert handler.poll() is None


def test_alt_key_and_complete_unknown_sequence_do_not_wait(
    progressive_handler: tuple[InputHandler, Terminal, _Clock],
) -> None:
    handler, terminal, clock = progressive_handler
    terminal.ungetch("\x1bz\x1b[99~é")
    events = []
    while (event := handler.poll()) is not None:
        events.append(event)
    assert events[0].binding == KeyBinding("z", alt=True)
    assert events[-1].text == "é"
    assert handler.get_pending_timeout(clock.now) is None


def test_kitty_escape_is_available_immediately(
    progressive_handler: tuple[InputHandler, Terminal, _Clock],
) -> None:
    handler, terminal, clock = progressive_handler
    terminal.ungetch("\x1b[27u")
    event = handler.poll()
    assert event is not None and event.binding == KeyBinding("escape")
    assert handler.get_pending_timeout(clock.now) is None


def test_close_clears_partial_sequence_deadline(
    progressive_handler: tuple[InputHandler, Terminal, _Clock],
) -> None:
    handler, terminal, clock = progressive_handler
    terminal.ungetch("\x1b[")
    assert handler.poll() is None
    handler.close()
    handler.close()
    assert handler.get_pending_timeout(clock.now) is None
    assert handler.poll() is None


@pytest.mark.parametrize("prefix", ["\x1b", "\x1b["])
def test_buffered_prefix_expires_from_reception_before_slow_callback(
    progressive_handler: tuple[InputHandler, Terminal, _Clock], prefix: str
) -> None:
    handler, terminal, clock = progressive_handler
    terminal.ungetch("a" + prefix)
    first = handler.poll()
    assert first is not None and first.text == "a"
    clock.now = 1.5
    assert handler.poll() is not None
    assert handler.get_pending_timeout(clock.now) is None


def test_new_prefix_after_old_continuation_has_its_own_reception_deadline(
    progressive_handler: tuple[InputHandler, Terminal, _Clock],
) -> None:
    handler, terminal, clock = progressive_handler
    terminal.ungetch("a\x1b[")
    first = handler.poll()
    assert first is not None and first.text == "a"
    clock.now = 1.5
    terminal.ungetch("I\x1b[")
    gained = handler.poll()
    assert gained is not None and gained.terminal_focus is True
    assert handler.poll() is None
    assert handler.get_pending_timeout(clock.now) == pytest.approx(1.0)
    clock.now = 1.55
    terminal.ungetch("O")
    lost = handler.poll()
    assert lost is not None and lost.terminal_focus is False
    assert handler.poll() is None
