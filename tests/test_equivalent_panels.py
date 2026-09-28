from collections.abc import Iterator
from inspect import signature
from os import terminal_size
from selectors import BaseSelector, SelectorKey
from threading import Event
from typing import cast

import pytest

from tuiloom import KeyBinding, ScreenContent, ScreenContext, TerminalApp, TerminalMenu
from tuiloom.event_loop.event_loop import EventLoop
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer


class PanelSelector:
    def register(self, fileobj: object, events: int, data: object) -> None:
        pass

    def select(self, timeout: float | None = None) -> list[tuple[SelectorKey, int]]:
        return []

    def close(self) -> None:
        pass


class PanelInput:
    def fileno(self) -> int:
        return 0

    def poll(self) -> InputEvent | None:
        return None

    def get_pending_timeout(self, now: float) -> float | None:
        return None


def make_runtime(menu: TerminalMenu) -> tuple[EventLoop, TerminalRenderer]:
    menu_renderer = MenuRenderer(menu)
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=menu_renderer, content_spacing=True
    )
    loop = EventLoop(
        menu,
        cast(InputHandler, PanelInput()),
        menu_renderer,
        renderer,
        selector_factory=lambda: cast(BaseSelector, PanelSelector()),
    )
    menu._event_loop = loop
    menu._terminal_renderer = renderer
    menu._running = True
    return loop, renderer


def test_menu_has_only_panel_content_api() -> None:
    parameters = signature(TerminalMenu).parameters
    assert "content" not in parameters
    assert "auto_scroll" not in parameters
    assert not hasattr(TerminalMenu, "set_content")
    assert not hasattr(TerminalMenu, "auto_scroll")


def test_legacy_menu_constructor_content_is_rejected() -> None:
    app = TerminalApp("App")
    with pytest.raises(TypeError, match="content"):
        TerminalMenu(
            app, ScreenContext("main", "Main"), content=ScreenContent.static("old")
        )  # type: ignore[call-arg]


def test_global_content_creates_an_ordinary_panel_without_a_primary_role() -> None:
    content = ScreenContent.static("global")
    app = TerminalApp("App", global_content=content)
    menu = TerminalMenu(app, ScreenContext("main", "Main"))
    assert len(menu.content_panels) == 1
    inherited = menu.content_panels[0]
    local = menu.add_content_panel(ScreenContent.static("local"), auto_scroll="strict")
    assert inherited.content is content
    assert not hasattr(menu, "_primary_content_panel")
    inherited.move(1)
    inherited.set_content(ScreenContent.static("updated"))
    inherited.set_auto_scroll("smart")
    assert list(menu.content_panels) == [local, inherited]
    assert local.content == ScreenContent.static("local")
    assert local.auto_scroll == "strict"
    inherited.remove()
    assert list(menu.content_panels) == [local]
    local.remove()
    assert list(menu.content_panels) == []
    assert app.global_content is content


def test_empty_runtime_can_add_remove_and_readd_panels_without_aliases() -> None:
    menu = TerminalMenu(TerminalApp("App"), ScreenContext("main", "Main"))
    loop, renderer = make_runtime(menu)
    try:
        assert not hasattr(menu, "_content_renderer")
        assert not hasattr(renderer, "_content_renderer")
        assert not hasattr(renderer, "viewport")
        for name in (
            "_content_renderer",
            "_source_worker",
            "_pending_content",
            "_dynamic_in_flight",
            "_next_dynamic_at",
        ):
            assert not hasattr(loop, name)
        assert menu.content_panels == ()
        assert (
            sum(line.startswith("╭") for line in renderer._compose_frame(30, 25)) == 1
        )
        first = menu.add_content_panel(ScreenContent.static("first"))
        second = menu.add_content_panel(ScreenContent.static("second"))
        renderer._compose_frame(30, 25)
        second_viewport = second._viewport
        first.set_content(ScreenContent.static("replacement"))
        renderer._compose_frame(30, 25)
        assert first._renderer.rendered_content.lines == ["replacement"]
        assert second._viewport is second_viewport
        menu._handle_event(InputEvent(KeyBinding("tab")))
        assert menu._focused_panel is first
        first.remove()
        assert menu._focused_panel is second
        second.remove()
        assert menu._focused_panel is None
        renderer._compose_frame(30, 25)
        new = menu.add_content_panel(ScreenContent.static("new"))
        renderer._compose_frame(30, 25)
        assert menu.content_panels == (new,)
        assert new._viewport is not None
        assert new._renderer.rendered_content.lines == ["new"]
    finally:
        loop.close()


@pytest.mark.parametrize("position", [0, 1])
def test_deferred_replacement_updates_render_cache_for_any_panel(
    position: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = Event()
    release = Event()

    def stream() -> Iterator[str]:
        blocked.set()
        release.wait()
        yield "late"

    menu = TerminalMenu(TerminalApp("App"), ScreenContext("main", "Main"))
    other = menu.add_content_panel(ScreenContent.static("other"))
    panel = menu.add_content_panel(ScreenContent.stream(stream()), position=position)
    loop, renderer = make_runtime(menu)
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((30, 25)),
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", lambda _: None)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    try:
        assert blocked.wait(1)
        loop._drain_source_events()
        renderer.render()
        assert panel._renderer.rendered_content.revision == 0
        assert "new" not in "\n".join(renderer._previous_lines or [])
        other_viewport = other._viewport
        worker = panel._worker
        assert worker is not None

        panel.set_content(ScreenContent.static("new"))
        renderer.render()  # The previous source is still visible while retiring.
        assert "new" not in "\n".join(renderer._previous_lines or [])
        release.set()
        assert worker.join(1)
        loop._progress_panel_transitions()
        renderer.render()

        frame = "\n".join(renderer._previous_lines or [])
        assert "new" in frame
        assert "late" not in frame
        assert other._viewport is other_viewport
        assert panel._renderer.rendered_content.revision == 0
    finally:
        release.set()
        loop.close()
