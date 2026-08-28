from __future__ import annotations

from collections.abc import Iterator
from typing import cast

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
        self.calls: list[tuple[float, float]] = []

    def cbreak(self) -> _BreakContext:
        return self.context

    def inkey(self, timeout: float, esc_delay: float) -> Keystroke:
        self.calls.append((timeout, esc_delay))
        return next(self.keys, Keystroke())


class _FakeStream:
    def fileno(self) -> int:
        return 42


def test_input_handler_polls_without_blocking_and_restores_once() -> None:
    terminal = _FakeTerminal(iter([stroke("é"), stroke("")]))
    stream = _FakeStream()
    handler = InputHandler(
        terminal=cast(object, terminal),  # type: ignore[arg-type]
        stream=cast(object, stream),  # type: ignore[arg-type]
        escape_delay=0.03,
    )
    assert terminal.context.entered
    assert handler.poll() is not None
    assert handler.poll() is None
    assert terminal.calls == [(0, 0.03), (0, 0.03)]
    assert handler.fileno() == 42
    assert handler.get_pending_timeout(1.0) is None
    handler.close()
    handler.close()
    assert terminal.context.exited
