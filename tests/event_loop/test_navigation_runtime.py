from __future__ import annotations

from selectors import BaseSelector
from threading import Event
from typing import cast

from tuiloom import ScreenContext, TerminalApp, TerminalMenu
from tuiloom.event_loop.event_loop import EventLoop
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer


class QuietSelector:
    def register(self, fileobj: object, events: int, data: object) -> None:
        pass

    def select(self, timeout: float | None = None) -> list[object]:
        return []

    def close(self) -> None:
        pass


class QuietInput:
    def fileno(self) -> int:
        return 0

    def poll(self) -> None:
        return None

    def get_pending_timeout(self, now: float) -> None:
        return None


def initialize(menu: TerminalMenu) -> EventLoop:
    source = menu._content_source or ""
    content_renderer = ContentRenderer(source)
    menu_renderer = MenuRenderer(menu)
    terminal_renderer = TerminalRenderer(
        menu=menu,
        menu_renderer=menu_renderer,
        content_renderer=content_renderer,
        content_spacing=True,
    )
    loop = EventLoop(
        menu,
        cast(InputHandler, QuietInput()),
        menu_renderer,
        terminal_renderer,
        content_renderer,
        selector_factory=lambda: cast(BaseSelector, QuietSelector()),
    )
    menu._running = True
    menu._event_loop = loop
    return loop


def test_hidden_menu_turn_applies_source_events_without_rendering() -> None:
    app = TerminalApp("App")
    root = TerminalMenu(app, ScreenContext("root", "Root"), content_source="root")
    child = TerminalMenu(
        app,
        ScreenContext("child", "Child"),
        content_source=iter(["hidden update\n"]),
    )
    root_loop = initialize(root)
    child_loop = initialize(child)
    app._initialized_menus = [root, child]
    app._menu_stack = [root]
    panel = child.content_panels[0]
    assert panel._worker is not None
    assert panel._worker.join(1)

    child_loop.run_once(process_input=False, render=False, block=False)

    assert panel._renderer.rendered_content.lines == ["hidden update"]
    root_loop.close()
    child_loop.close()


def test_hidden_owner_receives_output_task_completion_callback() -> None:
    app = TerminalApp("App")
    root = TerminalMenu(app, ScreenContext("root", "Root"), content_source="root")
    child = TerminalMenu(app, ScreenContext("child", "Child"), content_source="child")
    root_loop = initialize(root)
    child_loop = initialize(child)
    app._initialized_menus = [root, child]
    app._menu_stack = [root]
    completed = Event()
    callbacks: list[int] = []

    with app._output_capture.install():
        child.run_with_output(
            lambda: 42,
            on_success=lambda result: (callbacks.append(result), completed.set()),
            on_error=lambda error: None,
        )
        session = child._output_task_session
        assert session is not None and session.join(1)
        child_loop.run_once(process_input=False, render=False, block=False)

    assert completed.is_set()
    assert callbacks == [42]
    root_loop.close()
    child_loop.close()


def test_hidden_menu_turn_requests_and_applies_dynamic_updates() -> None:
    app = TerminalApp("App")
    calls = 0
    evaluated = Event()

    def dynamic() -> str:
        nonlocal calls
        calls += 1
        evaluated.set()
        return f"hidden {calls}"

    root = TerminalMenu(app, ScreenContext("root", "Root"), content_source="root")
    child = TerminalMenu(
        app,
        ScreenContext("child", "Child"),
        content_source=dynamic,
    )
    root_loop = initialize(root)
    child_loop = initialize(child)
    app._initialized_menus = [root, child]
    app._menu_stack = [root]

    child_loop.run_once(process_input=False, render=False, block=False)
    panel = child.content_panels[0]
    assert panel._worker is not None
    assert evaluated.wait(1)
    child_loop.run_once(process_input=False, render=False, block=False)

    assert calls == 1
    assert panel._renderer.rendered_content.lines == ["hidden 1"]
    root_loop.close()
    child_loop.close()
