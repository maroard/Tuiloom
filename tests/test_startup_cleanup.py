import pytest

from tuiloom import CommandContext, MenuDisplay, TerminalApp, TerminalMenu


def test_initial_hover_failure_closes_input_and_resets_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[bool] = []

    class Input:
        def close(self) -> None:
            closed.append(True)

    def fail(context: CommandContext) -> None:
        raise RuntimeError("initial hover failed")

    app = TerminalApp("App")
    menu = TerminalMenu(app, MenuDisplay("main", "Main"))
    menu.add_command("Action", lambda context: None, on_hover=fail)
    app.set_main_menu(menu)
    monkeypatch.setattr("tuiloom.terminal_app.InputHandler", Input)
    monkeypatch.setattr(app, "_leave_terminal_screen", lambda: None)

    with pytest.raises(RuntimeError, match="initial hover failed"):
        app.run()

    assert closed == [True]
    assert app._input_handler is None
    assert not app._running


def test_shutdown_attempts_every_menu_after_a_cleanup_failure() -> None:
    from typing import cast

    from tuiloom.event_loop.event_loop import EventLoop

    app = TerminalApp("App")
    first = TerminalMenu(app, MenuDisplay("first", "First"))
    second = TerminalMenu(app, MenuDisplay("second", "Second"))
    closed: list[str] = []

    class Loop:
        def __init__(self, name: str, fails: bool) -> None:
            self.name = name
            self.fails = fails

        def close(self) -> None:
            closed.append(self.name)
            if self.fails:
                raise RuntimeError("cleanup failed")

    first._event_loop = cast(EventLoop, Loop("first", True))
    second._event_loop = cast(EventLoop, Loop("second", False))
    first._running = second._running = True
    app._initialized_menus = [first, second]
    with pytest.raises(RuntimeError, match="cleanup failed"):
        app._shutdown_menu_runtimes()
    assert closed == ["first", "second"]
    assert first._event_loop is second._event_loop is None
    assert not first._running and not second._running


def test_run_preserves_callback_and_cleanup_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Input:
        def close(self) -> None:
            raise OSError("input cleanup failed")

    def fail() -> None:
        raise RuntimeError("application failed")

    app = TerminalApp("App")
    menu = TerminalMenu(app, MenuDisplay("main", "Main"))
    app.set_main_menu(menu)
    monkeypatch.setattr("tuiloom.terminal_app.InputHandler", Input)
    monkeypatch.setattr(app, "_enter_terminal_screen", lambda: None)
    monkeypatch.setattr(app, "_leave_terminal_screen", lambda: None)
    monkeypatch.setattr(app, "_run_application_loop", fail)
    with pytest.raises(BaseExceptionGroup) as result:
        app.run()
    assert [str(error) for error in result.value.exceptions] == [
        "application failed",
        "input cleanup failed",
    ]
    assert app._input_handler is None
    assert not app._running
