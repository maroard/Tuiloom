from __future__ import annotations

import io
import sys
from threading import Event, get_ident

import pytest

from tuiloom import KeyBinding, ScreenContext, TerminalApp, TerminalMenu
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.output_task import OutputTaskSession


def make_main() -> tuple[TerminalApp, TerminalMenu]:
    app = TerminalApp("App")
    menu = TerminalMenu(app, ScreenContext("main", "Main"), content_source="base")
    app.set_main_menu(menu)
    menu._running = True
    return app, menu


def number(menu: TerminalMenu, value: str) -> None:
    menu._handle_event(InputEvent(KeyBinding(value), value))


def test_wait_and_quit_runs_callback_on_ui_thread_then_stops() -> None:
    app, menu = make_main()
    release = Event()
    callbacks: list[tuple[object, int]] = []
    ui_thread = get_ident()

    def action() -> int:
        release.wait(1)
        return 42

    with app._output_capture.install():
        session = app._start_output_task(
            menu,
            action,
            lambda result: callbacks.append((result, get_ident())),
            lambda error: pytest.fail(str(error)),
            "Downloading",
        )
        menu._output_task_session = session
        menu.stop()
        assert "Stop and quit" in (menu.screen_context.message or "")
        number(menu, "2")
        assert menu._exit_mode == "waiting"
        assert menu._tick_task_exit(menu._wait_started_at + 0.41)
        assert "Downloading" in (menu.screen_context.message or "")
        release.set()
        assert session.join(1)
        assert app._dispatch_output_task_outcome() is menu
    assert callbacks == [(42, ui_thread)]
    assert not menu._running


def test_cancel_exit_restores_previous_message_and_normal_state() -> None:
    app, menu = make_main()
    release = Event()
    menu.screen_context.message = "Previous"
    with app._output_capture.install():
        session = app._start_output_task(
            menu,
            lambda: release.wait(1),
            lambda result: None,
            lambda error: None,
            "Work",
        )
        menu._output_task_session = session
        menu.stop()
        number(menu, "0")
        assert menu._exit_mode is None
        assert menu.screen_context.message == "Previous"
        assert menu._running
        release.set()
        assert session.join(1)
        app._dispatch_output_task_outcome()


def test_wait_callback_exception_still_stops_menu_and_propagates() -> None:
    app, menu = make_main()

    def fail(result: object) -> None:
        raise RuntimeError("callback failed")

    with app._output_capture.install():
        session = app._start_output_task(
            menu, lambda: 1, fail, lambda error: None, "Work"
        )
        menu._output_task_session = session
        menu.stop()
        number(menu, "2")
        assert session.join(1)
        with pytest.raises(RuntimeError, match="callback failed"):
            app._dispatch_output_task_outcome()
    assert not menu._running


def test_stop_and_quit_waits_and_discards_future_output_and_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_stdout = io.StringIO()
    original_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", original_stdout)
    monkeypatch.setattr(sys, "stderr", original_stderr)
    app, menu = make_main()
    started = Event()
    release = Event()
    callbacks: list[str] = []

    def action() -> None:
        started.set()
        release.wait(1)
        print("late")

    with app._output_capture.install():
        session = app._start_output_task(
            menu,
            action,
            lambda result: callbacks.append("success"),
            lambda error: callbacks.append("error"),
            "Work",
        )
        menu._output_task_session = session
        assert started.wait(1)
        menu.stop()
        number(menu, "1")
        assert menu._running
        assert menu.screen_context.message == "Stopping…"
        assert sys.stdout is not original_stdout
        print("ui remains visible")
        release.set()
        assert session.join(1)
        assert app._dispatch_output_task_outcome() is menu
        assert menu._tick_task_exit(menu._wait_started_at + 0.41)
        assert not menu._running
    assert sys.stdout is original_stdout
    assert "late" not in original_stdout.getvalue()
    assert "ui remains visible" in original_stdout.getvalue()
    assert callbacks == []


def test_source_work_offers_exit_choices_and_stop_waits_for_real_termination() -> None:
    _, menu = make_main()

    class Work:
        description = "Generating function calls"

        def __init__(self) -> None:
            self.alive = True
            self.cancelled = False
            self.joined = False

        def cancel(self) -> None:
            self.cancelled = True

        def is_alive(self) -> bool:
            return self.alive

        def join(self, timeout: float | None = None) -> bool:
            self.joined = True
            return not self.alive

    work = Work()

    class Loop:
        @property
        def active_work(self) -> Work:
            return work

    menu._event_loop = Loop()  # type: ignore[assignment]

    menu.stop()
    assert menu._running
    assert "Stop and quit" in (menu.screen_context.message or "")

    number(menu, "1")
    assert work.cancelled
    assert menu._running
    assert menu.screen_context.message == "Stopping…"

    number(menu, "0")
    assert menu._exit_mode == "stopping"
    assert menu._running

    work.alive = False
    assert menu._tick_task_exit(menu._wait_started_at + 0.41)
    assert work.joined
    assert not menu._running


def test_wait_and_quit_allows_source_to_finish_without_cancelling_it() -> None:
    _, menu = make_main()

    class Work:
        description = "Streaming"

        def __init__(self) -> None:
            self.alive = True
            self.cancelled = False
            self.joined = False

        def cancel(self) -> None:
            self.cancelled = True

        def is_alive(self) -> bool:
            return self.alive

        def join(self, timeout: float | None = None) -> bool:
            self.joined = True
            return not self.alive

    work = Work()

    class Loop:
        @property
        def active_work(self) -> Work | None:
            return work if work.alive else None

    menu._event_loop = Loop()  # type: ignore[assignment]
    menu.stop()
    number(menu, "2")

    assert menu._exit_mode == "waiting"
    assert not work.cancelled
    assert menu._running
    assert menu._tick_task_exit(menu._wait_started_at + 0.41)
    assert "Streaming" in (menu.screen_context.message or "")

    work.alive = False
    assert menu._tick_task_exit(menu._wait_started_at + 0.81)
    assert work.joined
    assert not menu._running


def test_run_with_output_validates_state_installs_stream_and_restores_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, menu = make_main()
    installed: list[tuple[object, str]] = []

    class Loop:
        def install_source(
            self,
            source: object,
            *,
            description: str = "Content in progress",
        ) -> None:
            installed.append((source, description))

    menu._event_loop = Loop()  # type: ignore[assignment]
    with app._output_capture.install():
        menu.run_with_output(
            lambda: 7,
            on_success=lambda result: None,
            on_error=lambda error: None,
            description="Compute",
        )
        session = menu._output_task_session
        assert isinstance(session, OutputTaskSession)
        assert session.join(1)
        app._dispatch_output_task_outcome()
    assert len(installed) == 2
    assert installed[0][1] == "Compute"
    assert installed[1][1] == "Content in progress"
    assert menu.auto_scroll is None

    menu._running = False
    with pytest.raises(RuntimeError, match="active"):
        menu.run_with_output(
            lambda: None,
            on_success=lambda result: None,
            on_error=lambda error: None,
        )


def test_run_with_output_restores_auto_scroll_when_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, menu = make_main()
    menu._event_loop = object()  # type: ignore[assignment]
    menu.auto_scroll = "smart"

    def fail(*args: object, **kwargs: object) -> OutputTaskSession:
        raise RuntimeError("start failed")

    monkeypatch.setattr(app, "_start_output_task", fail)
    with pytest.raises(RuntimeError, match="start failed"):
        menu.run_with_output(
            lambda: None,
            on_success=lambda result: None,
            on_error=lambda error: None,
        )
    assert menu.auto_scroll == "smart"


def test_task_error_dispatches_error_callback() -> None:
    app, menu = make_main()
    errors: list[Exception] = []

    def fail() -> None:
        raise ValueError("broken")

    with app._output_capture.install():
        session = app._start_output_task(
            menu, fail, lambda result: None, errors.append, "Work"
        )
        menu._output_task_session = session
        assert session.join(1)
        app._dispatch_output_task_outcome()
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
