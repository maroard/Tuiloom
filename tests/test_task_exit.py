from __future__ import annotations

import io
import sys
from threading import Event, get_ident
from typing import cast

import pytest

from tuiloom import ContentPanel, KeyBinding, ScreenContext, TerminalApp, TerminalMenu
from tuiloom.event_loop.event_loop import EventLoop
from tuiloom.event_loop.source_worker import SourceWorker
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.output_task import OutputTaskSession
from tuiloom.render.menu_renderer import MenuRenderer


def make_main() -> tuple[TerminalApp, TerminalMenu]:
    app = TerminalApp("App")
    menu = TerminalMenu(app, ScreenContext("main", "Main"), content_source="base")
    app.set_main_menu(menu)
    menu._running = True
    return app, menu


def number(menu: TerminalMenu, value: str) -> None:
    menu._handle_event(InputEvent(KeyBinding(value), value))


def press(menu: TerminalMenu, key: str, text: str | None = None) -> None:
    menu._handle_event(InputEvent(KeyBinding(key), text))


class FakeWork:
    def __init__(self, description: str) -> None:
        self.description = description
        self.alive = True
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float | None = None) -> bool:
        return not self.alive


class FakePanelLoop:
    def __init__(self) -> None:
        self.work: dict[ContentPanel, FakeWork] = {}

    @property
    def active_panels(self) -> tuple[ContentPanel, ...]:
        return tuple(panel for panel, work in self.work.items() if work.alive)

    @property
    def retiring_panels(self) -> tuple[ContentPanel, ...]:
        return ()

    def add_content_panel(self, panel: ContentPanel) -> None:
        return

    def attach(self, panel: ContentPanel, work: FakeWork) -> None:
        self.work[panel] = work
        panel._worker = cast(SourceWorker, work)


def install_fake_operations(
    menu: TerminalMenu,
    *descriptions: str,
) -> tuple[FakePanelLoop, tuple[FakeWork, ...]]:
    loop = FakePanelLoop()
    work: list[FakeWork] = []
    for description in descriptions:
        panel = menu.add_content_source("last output", description=description)
        operation = FakeWork(description)
        loop.attach(panel, operation)
        work.append(operation)
    menu._event_loop = loop  # type: ignore[assignment]
    return loop, tuple(work)


def attach_output_task(
    app: TerminalApp,
    menu: TerminalMenu,
    session: OutputTaskSession,
    description: str,
) -> ContentPanel:
    panel = menu.add_content_source(
        session.iter_output(),
        description=description,
        auto_scroll="strict",
    )
    menu._output_task_session = session
    menu._output_task_panel = panel
    app._attach_output_panel(session, panel)

    class Loop:
        @property
        def active_panels(self) -> tuple[ContentPanel, ...]:
            return (panel,) if session.is_alive() else ()

        @property
        def retiring_panels(self) -> tuple[ContentPanel, ...]:
            return ()

    menu._event_loop = cast(EventLoop, Loop())
    return panel


def test_exit_view_uses_normal_rows_without_mutating_screen_context() -> None:
    _, menu = make_main()
    install_fake_operations(menu, "Streaming")
    menu.screen_context.message = "Previous"

    menu.stop()

    rendered = MenuRenderer(menu).render()
    assert menu._task_exit is not None
    assert "Operation in progress" in rendered
    assert "> Force quit" in rendered
    assert "  Wait and quit" in rendered
    assert "  Cancel" in rendered
    assert menu.screen_context.title == "Main"
    assert menu.screen_context.message == "Previous"


def test_exit_view_uses_arrows_enter_and_ignores_numbers() -> None:
    _, menu = make_main()
    install_fake_operations(menu, "Work")
    menu.stop()

    for value in ("1", "2", "0"):
        number(menu, value)
    choice_view = menu._task_exit
    assert choice_view is not None
    assert choice_view.mode == "choice"

    press(menu, "down")
    press(menu, "enter")
    waiting_view = menu._task_exit
    assert waiting_view is not None
    assert waiting_view.mode == "waiting"
    assert waiting_view.rows == ("Cancel",)


def test_exit_choice_tracks_plural_completion_and_quits_at_zero() -> None:
    _, menu = make_main()
    _, (first, second) = install_fake_operations(menu, "First", "Second")
    menu.stop()
    assert menu._task_exit is not None
    assert menu._task_exit.visible_title(2) == "Operations in progress"

    second.alive = False
    assert menu._tick_task_exit(0.0)
    assert menu._task_exit.visible_title(1) == "Operation in progress"
    assert menu._task_exit.visible_panels == (menu.content_panels[1],)
    assert menu._running

    first.alive = False
    assert menu._tick_task_exit(0.1)
    assert not menu._running


def test_back_cancels_exit_view_and_restores_navigation() -> None:
    _, menu = make_main()
    install_fake_operations(menu, "Work")
    menu._selected_index = len(menu.commands)
    menu.stop()

    press(menu, "escape")

    assert menu._task_exit is None
    assert menu._selected_index == len(menu.commands)
    assert menu._focused_panel is None
    assert menu._running


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
        panel = attach_output_task(app, menu, session, "Downloading")
        menu.stop()
        press(menu, "down")
        press(menu, "enter")
        assert menu._task_exit is not None
        assert menu._task_exit.mode == "waiting"
        assert menu._tick_task_exit(menu._task_exit.wait_started_at + 0.41)
        assert menu._visible_panel_description(panel) == "Downloading.."
        release.set()
        assert session.join(1)
        assert app._dispatch_output_task_outcome() is menu
        assert menu._tick_task_exit(menu._task_exit.wait_started_at + 0.81)
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
        attach_output_task(app, menu, session, "Work")
        menu.stop()
        press(menu, "escape")
        assert menu._task_exit is None
        assert menu.screen_context.message == "Previous"
        assert menu._running
        release.set()
        assert session.join(1)
        app._dispatch_output_task_outcome()


def test_wait_callback_exception_still_stops_menu_and_propagates() -> None:
    app, menu = make_main()
    release = Event()

    def fail(result: object) -> None:
        raise RuntimeError("callback failed")

    with app._output_capture.install():
        session = app._start_output_task(
            menu, lambda: release.wait(1), fail, lambda error: None, "Work"
        )
        attach_output_task(app, menu, session, "Work")
        menu.stop()
        press(menu, "down")
        press(menu, "enter")
        release.set()
        assert session.join(1)
        with pytest.raises(RuntimeError, match="callback failed"):
            app._dispatch_output_task_outcome()
        assert menu._task_exit is not None
        menu._tick_task_exit(menu._task_exit.wait_started_at + 0.41)
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
        attach_output_task(app, menu, session, "Work")
        assert started.wait(1)
        menu.stop()
        press(menu, "enter")
        assert menu._running
        assert menu._task_exit is not None
        assert menu._task_exit.mode == "stopping"
        assert "Stopping operation" in MenuRenderer(menu).render()
        assert sys.stdout is not original_stdout
        print("ui remains visible")
        release.set()
        assert session.join(1)
        assert app._dispatch_output_task_outcome() is menu
        assert menu._tick_task_exit(menu._task_exit.wait_started_at + 0.41)
        assert not menu._running
    assert sys.stdout is original_stdout
    assert "late" not in original_stdout.getvalue()
    assert "ui remains visible" in original_stdout.getvalue()
    assert callbacks == []


def test_source_work_offers_exit_choices_and_stop_waits_for_real_termination() -> None:
    _, menu = make_main()
    _, (work,) = install_fake_operations(menu, "Generating function calls")

    menu.stop()
    assert menu._running
    assert "Operation in progress" in MenuRenderer(menu).render()

    press(menu, "enter")
    assert work.cancelled
    assert menu._running
    assert menu._task_exit is not None
    assert menu._task_exit.mode == "stopping"

    number(menu, "0")
    assert menu._task_exit.mode == "stopping"
    assert menu._running

    work.alive = False
    assert menu._tick_task_exit(menu._task_exit.wait_started_at + 0.41)
    assert not menu._running


def test_force_quit_cancels_operations_that_appear_while_stopping() -> None:
    _, menu = make_main()
    loop, (first,) = install_fake_operations(menu, "First")
    menu.stop()
    press(menu, "enter")
    assert first.cancelled

    second_panel = menu.add_content_source("late output", description="Second")
    second = FakeWork("Second")
    loop.attach(second_panel, second)

    assert menu._tick_task_exit(0.1)
    assert second.cancelled
    assert menu._task_exit is not None
    assert menu._task_exit.visible_panels == (
        menu.content_panels[1],
        second_panel,
    )

    first.alive = False
    second.alive = False
    assert menu._tick_task_exit(0.2)
    assert not menu._running


def test_wait_and_quit_allows_source_to_finish_without_cancelling_it() -> None:
    _, menu = make_main()
    _, (work,) = install_fake_operations(menu, "Streaming")
    menu.stop()
    press(menu, "down")
    press(menu, "enter")

    assert menu._task_exit is not None
    assert menu._task_exit.mode == "waiting"
    assert not work.cancelled
    assert menu._running
    assert menu._tick_task_exit(menu._task_exit.wait_started_at + 0.41)
    panel = menu._task_exit.visible_panels[0]
    assert menu._visible_panel_description(panel) == "Streaming.."

    work.alive = False
    assert menu._tick_task_exit(menu._task_exit.wait_started_at + 0.81)
    assert not menu._running


def test_run_with_output_adds_a_strict_temporary_panel() -> None:
    app, menu = make_main()
    base = menu.content_panels[0]
    added: list[ContentPanel] = []

    class Loop:
        def add_content_panel(self, panel: ContentPanel) -> None:
            added.append(panel)

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
        output_panel = menu.content_panels[-1]
        assert menu.content_panels == (base, output_panel)
        assert output_panel.description == "Compute"
        assert output_panel.auto_scroll == "strict"
        assert session.join(1)
        app._dispatch_output_task_outcome()
    assert added == [output_panel]
    assert output_panel._remove_when_finished
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
