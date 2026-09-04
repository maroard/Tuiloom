from __future__ import annotations

import sys
from threading import Event, Thread

import pytest

from tuiloom import ScreenContext, TerminalApp, TerminalMenu
from tuiloom.output_task import OutputTaskSession


def test_content_sources_are_read_only_and_local_source_wins() -> None:
    app = TerminalApp("App", global_content_source="global")
    inherited = TerminalMenu(app, ScreenContext("inherited", "Inherited"))
    local = TerminalMenu(app, ScreenContext("local", "Local"), content_source="local")
    assert app.name == "App"
    assert app.global_content_source == "global"
    assert inherited._content_source == "global"
    assert local._content_source == "local"
    with pytest.raises(AttributeError):
        app.global_content_source = "new"  # type: ignore[misc]


def test_run_requires_main_menu_and_main_thread() -> None:
    app = TerminalApp("App")
    with pytest.raises(RuntimeError, match="no main menu"):
        app.run()
    menu = TerminalMenu(app, ScreenContext("main", "Main"))
    app.set_main_menu(menu)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            app.run()
        except BaseException as error:
            errors.append(error)

    worker = Thread(target=run)
    worker.start()
    worker.join(1)
    assert len(errors) == 1
    assert "main thread" in str(errors[0])


def test_run_installs_capture_and_restores_terminal_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeInputHandler:
        def close(self) -> None:
            calls.append("close")

    app = TerminalApp("App")
    menu = TerminalMenu(app, ScreenContext("main", "Main"))
    app.set_main_menu(menu)
    calls: list[str] = []
    original_stdout = sys.stdout
    monkeypatch.setattr("tuiloom.terminal_app.InputHandler", FakeInputHandler)
    monkeypatch.setattr(app, "_enter_terminal_screen", lambda: calls.append("enter"))
    monkeypatch.setattr(app, "_leave_terminal_screen", lambda: calls.append("leave"))

    def fail() -> None:
        assert sys.stdout is not original_stdout
        raise RuntimeError("render failed")

    monkeypatch.setattr(menu, "run", fail)
    with pytest.raises(RuntimeError, match="render failed"):
        app.run()
    assert calls == ["enter", "close", "leave"]
    assert sys.stdout is original_stdout


def test_hard_exit_restores_terminal_before_terminating_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HardExitObserved(BaseException):
        pass

    class FakeInputHandler:
        def close(self) -> None:
            calls.append("input closed")

    app = TerminalApp("App")
    menu = TerminalMenu(app, ScreenContext("main", "Main"))
    app.set_main_menu(menu)
    calls: list[object] = []

    def run_menu() -> None:
        menu._hard_exit_requested = True

    def terminate(status: int) -> None:
        calls.append(("exit", status))
        raise HardExitObserved

    monkeypatch.setattr("tuiloom.terminal_app.InputHandler", FakeInputHandler)
    monkeypatch.setattr(app, "_enter_terminal_screen", lambda: calls.append("enter"))
    monkeypatch.setattr(app, "_leave_terminal_screen", lambda: calls.append("leave"))
    monkeypatch.setattr(
        app,
        "_shutdown_output_task",
        lambda *, wait_for_worker=True: calls.append(("shutdown", wait_for_worker)),
    )
    monkeypatch.setattr(menu, "run", run_menu)
    monkeypatch.setattr("tuiloom.terminal_app._exit", terminate, raising=False)

    with pytest.raises(HardExitObserved):
        app.run()

    assert calls == [
        "enter",
        ("shutdown", False),
        "input closed",
        "leave",
        ("exit", 0),
    ]


def test_terminal_escape_sequences_enter_and_leave_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[str] = []
    monkeypatch.setattr("tuiloom.terminal_app.stdout.write", writes.append)
    monkeypatch.setattr("tuiloom.terminal_app.stdout.flush", lambda: None)
    app = TerminalApp("App")
    app._enter_terminal_screen()
    app._leave_terminal_screen()
    assert "\033[?1049h" in "".join(writes)
    assert "\033[?1049l" in "".join(writes)


def test_run_joins_output_worker_before_restoring_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeInputHandler:
        def close(self) -> None:
            calls.append("input closed")

    app = TerminalApp("App")
    menu = TerminalMenu(app, ScreenContext("main", "Main"))
    app.set_main_menu(menu)
    started = Event()
    release = Event()
    checked = Event()
    calls: list[str] = []
    sessions: list[OutputTaskSession] = []

    def action() -> None:
        started.set()
        release.wait()

    def run_menu() -> None:
        session = app._start_output_task(
            menu,
            action,
            lambda result: None,
            lambda error: None,
            "Work",
        )
        menu._output_task_session = session
        sessions.append(session)

    def allow_shutdown() -> None:
        assert started.wait(1)
        assert "leave" not in calls
        checked.set()
        release.set()

    monkeypatch.setattr("tuiloom.terminal_app.InputHandler", FakeInputHandler)
    monkeypatch.setattr(app, "_enter_terminal_screen", lambda: calls.append("enter"))
    monkeypatch.setattr(app, "_leave_terminal_screen", lambda: calls.append("leave"))
    monkeypatch.setattr(menu, "run", run_menu)
    releaser = Thread(target=allow_shutdown)
    releaser.start()

    app.run()
    releaser.join(1)

    assert checked.is_set()
    assert calls == ["enter", "input closed", "leave"]
    assert len(sessions) == 1
    session = sessions[0]
    assert not session.is_alive()
    assert app._active_output_task is None


def test_navigation_stack_transitions_and_reopening() -> None:
    app = TerminalApp("App")
    root = TerminalMenu(app, ScreenContext("root", "Root"))
    child = TerminalMenu(app, ScreenContext("child", "Child"))
    leaf = TerminalMenu(app, ScreenContext("leaf", "Leaf"))

    app.push_menu(root)
    app.push_menu(child)
    app.replace_menu(leaf)
    assert app._menu_stack == [root, leaf]
    app.pop_menu()
    assert app._menu_stack == [root]
    app.push_menu(child)
    app.push_menu(leaf)
    app.reset_to(child)
    assert app._menu_stack == [root, child]
    app.reset_to(leaf)
    assert app._menu_stack == [leaf]


def test_navigation_rejects_foreign_and_simultaneous_duplicates_atomically() -> None:
    app = TerminalApp("App")
    other = TerminalApp("Other")
    root = TerminalMenu(app, ScreenContext("root", "Root"))
    foreign = TerminalMenu(other, ScreenContext("foreign", "Foreign"))
    app.push_menu(root)

    for operation in (
        lambda: app.push_menu(foreign),
        lambda: app.replace_menu(foreign),
        lambda: app.reset_to(foreign),
        lambda: app.push_menu(root),
    ):
        with pytest.raises(ValueError):
            operation()
        assert app._menu_stack == [root]


def test_pop_at_root_requests_application_shutdown() -> None:
    app = TerminalApp("App")
    root = TerminalMenu(app, ScreenContext("root", "Root"))
    app.push_menu(root)
    app._running = True

    app.pop_menu()

    assert not app._running
    assert app._menu_stack == [root]


def test_run_accepts_entry_menu_without_registered_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeInputHandler:
        def close(self) -> None:
            pass

    app = TerminalApp("App")
    entry = TerminalMenu(app, ScreenContext("entry", "Entry"))
    observed: list[TerminalMenu] = []
    monkeypatch.setattr("tuiloom.terminal_app.InputHandler", FakeInputHandler)
    monkeypatch.setattr(app, "_enter_terminal_screen", lambda: None)
    monkeypatch.setattr(app, "_leave_terminal_screen", lambda: None)
    monkeypatch.setattr(
        app,
        "_run_application_loop",
        lambda: (observed.append(app._menu_stack[-1]), setattr(app, "_running", False)),
    )

    app.run(entry)

    assert observed == [entry]


def test_application_loop_services_hidden_menus_but_inputs_and_renders_only_top(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = TerminalApp("App")
    root = TerminalMenu(app, ScreenContext("root", "Root"))
    child = TerminalMenu(app, ScreenContext("child", "Child"))
    calls: list[tuple[str, bool, bool, bool]] = []

    class Loop:
        def __init__(self, name: str) -> None:
            self.name = name

        def run_once(self, *, process_input: bool, render: bool, block: bool) -> None:
            calls.append((self.name, process_input, render, block))
            if self.name == "child":
                app._running = False

    def initialize(menu: TerminalMenu, name: str) -> None:
        menu._running = True
        menu._event_loop = Loop(name)  # type: ignore[assignment]

    monkeypatch.setattr(root, "_initialize_runtime", lambda: initialize(root, "root"))
    monkeypatch.setattr(
        child, "_initialize_runtime", lambda: initialize(child, "child")
    )
    app.push_menu(root)
    root._initialize_runtime()
    app._initialized_menus.append(root)
    app.push_menu(child)
    app._running = True

    app._run_application_loop()

    assert calls == [
        ("root", False, False, False),
        ("child", True, True, True),
    ]


def test_reopening_retained_menu_resets_navigation_without_reinitializing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = TerminalApp("App")
    root = TerminalMenu(app, ScreenContext("root", "Root"))
    child = TerminalMenu(app, ScreenContext("child", "Child"))
    initializations: list[TerminalMenu] = []

    class Loop:
        def run_once(self, **kwargs: object) -> None:
            if kwargs.get("process_input"):
                app._running = False

    def initialize() -> None:
        initializations.append(child)
        child._running = True
        child._event_loop = Loop()  # type: ignore[assignment]

    monkeypatch.setattr(child, "_initialize_runtime", initialize)
    app.push_menu(root)
    app.push_menu(child)
    root._event_loop = Loop()  # type: ignore[assignment]
    app._initialized_menus.append(root)
    child._selected_index = 3
    child._focused_panel = object()  # type: ignore[assignment]
    child._input_buffer = "old"
    app._running = True
    app._run_application_loop()
    app.pop_menu()
    app.push_menu(child)
    app._running = True
    app._run_application_loop()

    assert initializations == [child]
    assert child._selected_index == 0
    assert child._focused_panel is None
    assert child._input_buffer == ""


def test_push_is_lazy_and_first_open_starts_source_worker_once() -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(
        app,
        ScreenContext("stream", "Stream"),
        content_source=iter(["done"]),
    )

    app.push_menu(menu)

    assert menu._event_loop is None
    assert menu.content_panels[0]._worker is None


def test_shutdown_closes_every_initialized_menu_runtime_once() -> None:
    app = TerminalApp("App")
    first = TerminalMenu(app, ScreenContext("first", "First"))
    second = TerminalMenu(app, ScreenContext("second", "Second"))
    calls: list[str] = []

    class Loop:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            calls.append(self.name)

    first._event_loop = Loop("first")  # type: ignore[assignment]
    second._event_loop = Loop("second")  # type: ignore[assignment]
    app._initialized_menus = [first, second]

    app._shutdown_menu_runtimes()
    app._shutdown_menu_runtimes()

    assert calls == ["first", "second"]
    assert first._event_loop is None
    assert second._event_loop is None
