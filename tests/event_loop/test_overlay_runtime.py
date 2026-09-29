from __future__ import annotations

from collections.abc import Callable, Iterator
from os import terminal_size
from selectors import BaseSelector
from threading import Event
from typing import cast

import pytest

from tuiloom import (
    ContentSize,
    MenuDisplay,
    ScreenContent,
    StatusBar,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.event_loop.event_loop import EventLoop
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer

from .test_event_loop import FakeInput, FakeSelector


def make_loop(
    content: ScreenContent, clock: Callable[[], float]
) -> tuple[TerminalMenu, EventLoop, TerminalRenderer]:
    menu = TerminalMenu(
        TerminalApp("App"), MenuDisplay("main", "Main"), presentation="overlay"
    )
    menu.add_content_panel(content)
    menu._running = True
    menu_renderer = MenuRenderer(menu)
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=menu_renderer, content_spacing=True
    )
    loop = EventLoop(
        menu,
        cast(InputHandler, FakeInput([])),
        menu_renderer,
        renderer,
        clock=clock,
        selector_factory=lambda: cast(BaseSelector, FakeSelector()),
    )
    menu._event_loop = loop
    menu._terminal_renderer = renderer
    return menu, loop, renderer


def silence_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((40, 24)),
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", lambda _: None)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)


def apply_next_result(loop: EventLoop) -> None:
    # Producers signal their Event before SourceWorker publishes to the queue.
    # Wait for publication instead of racing that signal in the assertions.
    event = loop._source_events.get(timeout=1)
    loop._source_events.put(event)
    loop._drain_source_events()


def test_show_hide_toggle_does_not_cancel_restart_or_stop_stream_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    silence_terminal(monkeypatch)
    started = Event()
    release = Event()
    starts: list[int] = []

    def stream() -> Iterator[str]:
        starts.append(1)
        started.set()
        yield "first\n"
        assert release.wait(2)
        yield "second\n"

    menu, loop, renderer = make_loop(ScreenContent.stream(stream()), lambda: 0)
    panel = menu.content_panels[0]
    worker = panel._runtime.worker
    assert worker is not None
    try:
        assert started.wait(1)
        loop.run_once(block=False)
        menu.hide_menu()
        assert loop._dirty and not loop._closed and menu._running
        menu.toggle_menu()
        menu.toggle_menu()
        assert worker.is_alive() and panel._runtime.worker is worker
        release.set()
        assert worker.join(1)
        loop.run_once(block=False)
        assert starts == [1]
        assert panel._runtime.renderer.rendered_content.lines == ["first", "second"]
        assert renderer._previous_lines is not None
        assert "second" in "\n".join(renderer._previous_lines)
        assert menu._event_loop is loop and menu._running
    finally:
        release.set()
        loop.close()


def test_responsive_producer_keeps_geometry_when_menu_visibility_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    silence_terminal(monkeypatch)
    now = 0.0
    evaluated = Event()
    sizes: list[ContentSize] = []

    def responsive(size: ContentSize) -> str:
        sizes.append(size)
        evaluated.set()
        return f"{size.width}x{size.height}"

    menu, loop, renderer = make_loop(ScreenContent.responsive(responsive), lambda: now)
    panel = menu.content_panels[0]
    try:
        menu.set_status_bar("READY")
        loop.run_once(block=False)
        assert evaluated.wait(1)
        apply_next_result(loop)
        now = 1 / 60
        loop.run_once(block=False)
        assert sizes == [ContentSize(38, 21)]
        worker = panel._runtime.worker
        menu.hide_menu()
        loop.run_once(block=False)
        assert panel._runtime.worker is worker and sizes == [ContentSize(38, 21)]
        menu.show_menu()
        loop.run_once(block=False)
        assert sizes == [ContentSize(38, 21)]
        evaluated.clear()
        monkeypatch.setattr(
            "tuiloom.render.terminal_renderer.get_terminal_size",
            lambda: terminal_size((30, 30)),
        )
        now = 1
        loop.request_render(immediate=True)
        loop.run_once(block=False)
        assert evaluated.wait(1)
        assert sizes[-1] == ContentSize(28, 27)
        assert renderer._previous_lines is not None
        assert len(renderer._previous_lines) == 30
    finally:
        loop.close()


def test_dynamic_content_and_status_continue_while_box_is_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    silence_terminal(monkeypatch)
    now = 0.0
    evaluated = Event()
    values: list[str] = []

    def dynamic() -> str:
        value = f"turn {len(values) + 1}"
        values.append(value)
        evaluated.set()
        return value

    menu, loop, renderer = make_loop(ScreenContent.dynamic(dynamic), lambda: now)
    try:
        menu.set_status_bar(
            StatusBar.dynamic(lambda: values[-1] if values else "READY")
        )
        menu.hide_menu()
        loop.run_once(block=False)
        assert evaluated.wait(1)
        # Apply a result without scheduling the next dynamic request yet.
        apply_next_result(loop)
        assert values == ["turn 1"]
        now = 1 / 60
        loop._render_if_due()
        assert renderer._previous_lines is not None
        assert renderer._previous_lines[-1] == "turn 1"
        assert "turn 1" in renderer._previous_lines[1]
        evaluated.clear()
        loop._request_dynamic_updates()
        assert evaluated.wait(1)
        apply_next_result(loop)
        now = 2 / 60
        loop._render_if_due()
        assert renderer._previous_lines[-1] == "turn 2"
        assert menu._running and not menu.menu_visible
    finally:
        loop.close()
