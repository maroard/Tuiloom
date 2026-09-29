from __future__ import annotations

from os import terminal_size
from threading import get_ident

import pytest

from tuiloom import StatusBar

from .test_event_loop import make_loop


def test_dynamic_status_schedules_ui_frames_at_existing_frame_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    menu, loop, _, renderer = make_loop([], clock=lambda: now)
    calls: list[int] = []
    state = "READY"
    size = terminal_size((40, 20))
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size", lambda: size
    )
    monkeypatch.setattr("tuiloom.event_loop.event_loop.get_terminal_size", lambda: size)
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.stdout.write", lambda text: None
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)

    def dynamic() -> str:
        calls.append(get_ident())
        return state

    try:
        menu.set_status_bar(StatusBar.dynamic(dynamic))
        loop.run_once(block=False)
        assert calls == [get_ident()]
        assert loop._get_wait_timeout() == pytest.approx(1 / 60)
        state = "RUNNING"
        now = 1 / 120
        loop.run_once(block=False)
        assert len(calls) == 1
        now = 1 / 60
        loop.run_once(block=False)
        assert calls == [get_ident(), get_ident()]
        assert renderer._previous_lines is not None
        assert renderer._previous_lines[-1] == "RUNNING"
        assert loop.active_work is None
        assert loop.active_panels == ()
        menu.clear_status_bar()
        loop.run_once(block=False)
        assert renderer._previous_lines[-1].startswith("╰")
        assert len(calls) == 2
        assert loop._get_wait_timeout() > 1 / 60
    finally:
        loop.close()


def test_live_static_status_and_responsive_refresh_request_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, loop, _, renderer = make_loop([])
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((40, 20)),
    )
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.stdout.write", lambda text: None
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    calls: list[int] = []
    try:
        loop.run_once(block=False)
        assert not loop._dirty
        menu.set_status_bar("READY")
        assert loop._dirty
        loop.run_once(block=False)
        assert renderer._previous_lines is not None
        assert renderer._previous_lines[-1] == "READY"
        state = "RUNNING"

        def responsive(width: int) -> str:
            calls.append(width)
            return state

        menu.set_status_bar(StatusBar.responsive(responsive))
        loop.run_once(block=False)
        assert calls == [40]
        state = "PAUSED"
        menu.refresh_status_bar()
        loop.run_once(block=False)
        assert calls == [40, 40]
        assert renderer._previous_lines[-1] == "PAUSED"
    finally:
        loop.close()


def test_hidden_menu_keeps_status_running_but_covered_menu_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    menu, loop, _, renderer = make_loop([], clock=lambda: now)
    calls: list[int] = []
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.stdout.write", lambda text: None
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    try:

        def dynamic() -> str:
            calls.append(1)
            return "READY"

        menu.set_status_bar(StatusBar.dynamic(dynamic))
        menu.hide_menu()
        loop.run_once(block=False)
        assert calls == [1]
        assert renderer._previous_lines is not None
        assert renderer._previous_lines[-1] == "READY"
        assert loop._get_wait_timeout() == pytest.approx(1 / 60)
        child = type(menu)(menu.app, menu.display_state)
        menu.app._menu_stack = [menu, child]
        now = 1 / 60
        loop.run_once(block=False)
        assert calls == [1]
        menu.app._menu_stack = [menu]
        loop.run_once(block=False)
        assert calls == [1, 1]
    finally:
        loop.close()
