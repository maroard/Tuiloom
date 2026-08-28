from __future__ import annotations

import sys
from threading import Thread

import pytest

from tuiloom import ScreenContext, TerminalApp, TerminalMenu


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
