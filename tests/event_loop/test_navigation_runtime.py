from __future__ import annotations

from collections.abc import Iterator
from selectors import BaseSelector
from threading import Event
from typing import cast

from tuiloom import ScreenContext, TerminalApp, TerminalMenu
from tuiloom.event_loop.event_loop import EventLoop
from tuiloom.event_loop.source_worker import SourceWorker
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

    def record_success(result: int) -> None:
        callbacks.append(result)
        completed.set()

    with app._output_capture.install():
        child.run_with_output(
            lambda: 42,
            on_success=record_success,
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


def test_reopening_menu_retains_its_real_source_worker() -> None:
    app = TerminalApp("App")
    starts = 0
    started = Event()

    def stream() -> Iterator[str]:
        nonlocal starts
        starts += 1
        started.set()
        yield "loaded"

    root = TerminalMenu(app, ScreenContext("root", "Root"), content_source="root")
    child = TerminalMenu(
        app,
        ScreenContext("child", "Child"),
        content_source=stream(),
    )
    root_loop = initialize(root)
    app._initialized_menus = [root]
    app._menu_stack = [root]

    app.push_menu(child)
    child_loop = initialize(child)
    app._initialized_menus.append(child)
    panel = child.content_panels[0]
    first_worker = panel._worker
    assert first_worker is not None
    assert started.wait(1)
    assert first_worker.join(1)

    app.pop_menu()
    app.push_menu(child)

    assert starts == 1
    assert child._event_loop is child_loop
    assert panel._worker is first_worker
    root_loop.close()
    child_loop.close()


def test_app_shutdown_cancels_and_joins_each_menu_worker_once() -> None:
    app = TerminalApp("App")
    root = TerminalMenu(app, ScreenContext("root", "Root"), content_source="root")
    child = TerminalMenu(
        app,
        ScreenContext("child", "Child"),
        content_source="child",
    )
    root_loop = initialize(root)
    child_loop = initialize(child)
    app._initialized_menus = [root, child]

    class CountingWorker:
        def __init__(self) -> None:
            self.cancel_calls = 0
            self.join_calls = 0

        def cancel(self) -> None:
            self.cancel_calls += 1

        def join(self, timeout: float | None = None) -> bool:
            self.join_calls += 1
            return True

    root_worker = CountingWorker()
    child_worker = CountingWorker()
    root.content_panels[0]._worker = cast(SourceWorker, root_worker)
    child.content_panels[0]._worker = cast(SourceWorker, child_worker)

    app._shutdown_menu_runtimes()
    app._shutdown_menu_runtimes()

    assert root_worker.cancel_calls == 1
    assert root_worker.join_calls == 1
    assert child_worker.cancel_calls == 1
    assert child_worker.join_calls == 1
    assert root_loop._closed
    assert child_loop._closed
