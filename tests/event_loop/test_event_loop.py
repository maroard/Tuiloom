import os
from selectors import BaseSelector, SelectorKey
from typing import Any, cast

import pytest

import tuiloom.event_loop.event_loop as event_loop_module
from tuiloom.event_loop.event_loop import EventLoop
from tuiloom.event_loop.source_event import SourceEvent
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.render.content_renderer import ContentRenderer, ContentSource
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.screen_context.screen_context import ScreenContext
from tuiloom.terminal_app import TerminalApp
from tuiloom.terminal_menu import TerminalMenu


class FakeClock:
    """Provide deterministic monotonic time for event-loop tests."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeSelector:
    """Record registrations and return explicitly queued readiness."""

    def __init__(self) -> None:
        self.ready: list[tuple[SelectorKey, int]] = []
        self.registered: list[SelectorKey] = []
        self.closed = False

    def register(self, fileobj: Any, events: int, data: object = None) -> SelectorKey:
        key = SelectorKey(fileobj, fileobj, events, data)
        self.registered.append(key)
        return key

    def select(self, timeout: float | None = None) -> list[tuple[SelectorKey, int]]:
        ready = self.ready
        self.ready = []
        return ready

    def close(self) -> None:
        self.closed = True


class FakeInputHandler:
    """Return a controlled sequence of non-blocking input events."""

    def __init__(self, events: list[InputEvent | None]) -> None:
        self.events = events
        self.poll_calls = 0

    def fileno(self) -> int:
        return 0

    def poll(self) -> InputEvent | None:
        self.poll_calls += 1
        return self.events.pop(0) if self.events else None

    def get_pending_timeout(self, now: float) -> float | None:
        return None


class RecordingTerminalRenderer(TerminalRenderer):
    """Record frames without composing or writing terminal output."""

    def __init__(self) -> None:
        self.render_calls = 0
        self.content_renderer = ContentRenderer("")

    def render(self, input_buffer: str = "") -> None:
        self.render_calls += 1

    def set_content_renderer(self, content_renderer: ContentRenderer) -> None:
        self.content_renderer = content_renderer


def make_loop(
    *,
    input_events: list[InputEvent | None] | None = None,
    source: ContentSource = "",
) -> tuple[EventLoop, FakeClock, FakeInputHandler, RecordingTerminalRenderer]:
    app = TerminalApp("App")
    menu = TerminalMenu(app, ScreenContext("App", "Menu", "Menu"))
    menu.running = True
    input_handler = FakeInputHandler(input_events or [None])
    menu_renderer = MenuRenderer(menu.screen_context)
    terminal_renderer = RecordingTerminalRenderer()
    content_renderer = ContentRenderer(source)
    selector = FakeSelector()
    clock = FakeClock()
    loop = EventLoop(
        menu=menu,
        input_handler=cast(InputHandler, input_handler),
        menu_renderer=menu_renderer,
        terminal_renderer=terminal_renderer,
        content_renderer=content_renderer,
        clock=clock,
        selector_factory=lambda: cast(BaseSelector, selector),
    )
    return loop, clock, input_handler, terminal_renderer


def test_loop_drains_every_available_input_event() -> None:
    loop, _, input_handler, _ = make_loop(
        input_events=[
            InputEvent("char", "1"),
            InputEvent("char", "2"),
            None,
        ]
    )

    loop._drain_input()

    assert loop.menu._input_buffer == "12"
    assert input_handler.poll_calls == 3
    loop.close()


def test_loop_batches_all_current_source_chunks() -> None:
    loop, _, _, _ = make_loop(source=iter(()))
    generation = loop.generation
    loop.source_events.put(SourceEvent(generation, "data", "a"))
    loop.source_events.put(SourceEvent(generation, "data", "b"))
    loop.source_events.put(SourceEvent(generation, "data", "c"))

    loop._drain_source_events()

    assert loop.content_renderer.update().lines == ["abc"]
    assert loop.content_renderer.update().revision == 1
    loop.close()


def test_loop_does_not_render_clean_state_before_deadline() -> None:
    loop, clock, _, terminal_renderer = make_loop()
    loop.request_render()
    loop._render_if_due()
    clock.advance(0.005)

    loop._render_if_due()

    assert terminal_renderer.render_calls == 1
    loop.close()


def test_source_error_is_raised_with_worker_traceback() -> None:
    loop, _, _, _ = make_loop(source=iter(()))
    error = ValueError("broken source")
    loop.source_events.put(
        SourceEvent(
            loop.generation,
            "error",
            error=error,
            traceback=error.__traceback__,
        )
    )

    with pytest.raises(ValueError, match="broken source"):
        loop._drain_source_events()

    loop.close()


def test_terminal_resize_requests_a_new_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_size = [os.terminal_size((80, 24))]
    monkeypatch.setattr(
        event_loop_module,
        "get_terminal_size",
        lambda: terminal_size[0],
        raising=False,
    )
    loop, clock, _, terminal_renderer = make_loop()
    loop._render_if_due()
    terminal_size[0] = os.terminal_size((20, 5))
    clock.advance(loop._STATE_CHECK_INTERVAL)

    loop._check_visible_state()
    loop._render_if_due()

    assert terminal_renderer.render_calls == 2
    loop.close()
