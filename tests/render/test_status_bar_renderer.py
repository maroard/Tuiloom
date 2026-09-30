from __future__ import annotations

from os import terminal_size

import pytest

from tuiloom import (
    AnimatedText,
    AnimationFrame,
    KeyBinding,
    MenuDisplay,
    ScreenContent,
    StatusBar,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.render.terminal_text import clip_display, display_width, normalize_line


def make_renderer() -> tuple[TerminalMenu, TerminalRenderer]:
    menu = TerminalMenu(TerminalApp("App"), MenuDisplay("main", "Main"))
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=MenuRenderer(menu), content_spacing=True
    )
    menu._terminal_renderer = renderer
    return menu, renderer


def test_status_bar_appearance_and_removal_preserve_legacy_frame() -> None:
    menu, renderer = make_renderer()
    original = renderer._compose_frame(40, 20)
    menu.set_status_bar("RUNNING")
    frame = renderer._compose_frame(40, 20)
    assert len(frame) == 20
    assert frame[: len(original)] == original
    assert frame[len(original) : -1] == [""] * (19 - len(original))
    assert frame[-1] == "RUNNING"
    assert menu.content_panels == ()
    menu.clear_status_bar()
    menu.clear_status_bar()
    assert renderer._compose_frame(40, 20) == original


@pytest.mark.parametrize("collapsed", [False, True])
@pytest.mark.parametrize("spacing", [False, True])
def test_status_row_is_reserved_before_panel_allocation(
    collapsed: bool, spacing: bool
) -> None:
    menu, renderer = make_renderer()
    renderer._content_spacing = spacing
    first = menu.add_content_panel(ScreenContent.static("one"), height_weight=3)
    second = menu.add_content_panel(ScreenContent.static("two"), height_weight=1)
    if collapsed:
        first.collapse()
        second.collapse()
    reduced = renderer._compose_frame(40, 19)
    menu.set_status_bar("READY")
    frame = renderer._compose_frame(40, 20)
    assert frame[: len(reduced)] == reduced
    assert len(frame) == 20
    assert frame[-1] == "READY"
    menu.clear_status_bar()
    assert renderer._compose_frame(40, 19) == reduced


@pytest.mark.parametrize(
    "text",
    [
        "x" * 100,
        "界" * 30,
        "👩‍💻" * 30,
        "e\u0301" * 100,
        "\033[31m" + "界" * 30 + "\033[0m",
        "\033]8;;https://example.com\033\\" + "x" * 100 + "\033]8;;\033\\",
        "one\ntwo\r\nthree\tend\033[2J",
    ],
)
def test_status_bar_uses_unicode_ansi_clipping_without_wrapping(text: str) -> None:
    menu, renderer = make_renderer()
    menu.set_status_bar(text)
    frame = renderer._compose_frame(12, 20)
    assert len(frame) == 20
    assert frame[-1] == clip_display(normalize_line(text), 0, 12)
    assert display_width(frame[-1]) <= 12
    assert "\n" not in frame[-1]
    assert "\033[2J" not in frame[-1]


@pytest.mark.parametrize("width,height", [(1, 1), (8, 2), (30, 3), (0, 0)])
def test_too_small_terminal_hides_status_within_physical_bounds(
    width: int, height: int
) -> None:
    menu, renderer = make_renderer()
    menu.add_content_panel(ScreenContent.static("content"))
    menu.set_status_bar("RUNNING")
    frame = renderer._compose_frame(width, height)
    assert frame == (
        ["Terminal window is too small."[:width]] if width and height else [""]
    )
    assert all(display_width(line) <= width for line in frame)


def test_status_bar_returns_when_terminal_grows_after_too_small_view() -> None:
    menu, renderer = make_renderer()
    menu.add_content_panel(ScreenContent.static("content"))
    menu.set_status_bar("RUNNING")
    assert renderer._compose_frame(30, 3) == ["Terminal window is too small."]
    assert renderer._compose_frame(30, 20)[-1] == "RUNNING"


def test_status_row_is_not_reclaimed_to_avoid_too_small_view() -> None:
    menu, renderer = make_renderer()
    menu.add_content_panel(ScreenContent.static("content"))
    height = next(
        height
        for height in range(1, 20)
        if renderer._compose_frame(30, height) != ["Terminal window is too small."]
    )
    menu.set_status_bar("READY")
    assert renderer._compose_frame(30, height) == ["Terminal window is too small."]
    assert renderer._compose_frame(30, height + 1)[-1] == "READY"


def test_responsive_status_recomputes_when_focus_changes() -> None:
    from tuiloom import KeyBinding, StatusBar
    from tuiloom.input_handler.input_event import InputEvent

    menu, renderer = make_renderer()
    first = menu.add_content_panel(ScreenContent.static("first"))
    second = menu.add_content_panel(ScreenContent.static("second"))
    calls: list[object] = []

    def status(width: int) -> str:
        calls.append(menu.focused_panel)
        return menu.focused_panel.description if menu.focused_panel else "Menu"

    menu.set_status_bar(StatusBar.responsive(status))
    assert renderer._compose_frame(40, 20)[-1] == "Menu"
    assert renderer._compose_frame(40, 20)[-1] == "Menu"
    for expected in (first, second, None):
        menu._handle_event(InputEvent(KeyBinding("tab")))
        assert menu.focused_panel is expected
        assert renderer._compose_frame(40, 20)[-1] == (
            expected.description if expected else "Menu"
        )
    assert calls == [None, first, second, None]


def test_hidden_menu_preserves_status() -> None:
    menu, renderer = make_renderer()
    menu.set_status_bar("READY")
    menu.hide_menu()
    assert renderer._compose_frame(40, 20)[-1] == "READY"
    menu.show_menu()
    assert renderer._compose_frame(40, 20)[-1] == "READY"


def test_animated_status_uses_width_and_frame_with_rate_cache() -> None:
    menu, renderer = make_renderer()
    calls: list[tuple[int, int]] = []

    def render_status(width: int, frame: object) -> str:
        index = frame.index  # type: ignore[attr-defined]
        calls.append((width, index))
        return f"\x1b[31m{width}:{index}\x1b[39m\x1b[2J"

    menu.set_status_bar(StatusBar.animated(render_status, fps=10))
    assert "40:0" in renderer._compose_frame(40, 20)[-1]
    renderer.set_animation_elapsed(0.05)
    assert "40:0" in renderer._compose_frame(40, 20)[-1]
    assert calls == [(40, 0)]
    renderer.set_animation_elapsed(0.11)
    line = renderer._compose_frame(40, 20)[-1]
    assert "40:1" in line
    assert "\x1b[2J" not in line
    assert calls == [(40, 0), (40, 1)]
    assert "20:1" in renderer._compose_frame(20, 20)[-1]
    assert calls[-1] == (20, 1)


def test_constant_animation_output_does_not_write_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer()
    title_frames: list[int] = []
    status_frames: list[int] = []

    def title(frame: AnimationFrame) -> str:
        title_frames.append(frame.index)
        return "Same title"

    def status(width: int, frame: AnimationFrame) -> str:
        status_frames.append(frame.index)
        return "Same status"

    menu.display_state.title = AnimatedText("Fallback", title, fps=5)
    menu.set_status_bar(StatusBar.animated(status, fps=5))
    writes: list[str] = []
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((40, 20)),
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    renderer.render()
    writes.clear()
    renderer._menu_renderer.set_animation_elapsed(0.21)
    renderer.set_animation_elapsed(0.21)
    renderer.render()
    assert title_frames == [0, 1]
    assert status_frames == [0, 1]
    assert writes == []


def test_status_does_not_change_messages_focus_or_scrolling() -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(ScreenContent.static("\n".join(map(str, range(40)))))
    menu.display_state.message = "menu message"
    renderer._compose_frame(40, 20)
    menu._handle_event(InputEvent(KeyBinding("tab")))
    renderer.scroll_panel(panel, "down")
    viewport = panel._runtime.viewport
    assert viewport is not None
    offset = viewport.offset_y
    menu.set_status_bar("READY")
    frame = renderer._compose_frame(40, 20)
    assert panel._runtime.viewport is viewport
    assert viewport.offset_y == offset
    assert menu._focused_panel is panel
    assert any("menu message" in line for line in frame[:-1])
    menu._handle_event(InputEvent(KeyBinding("tab")))
    assert menu._focused_panel is None
    menu.clear_status_bar()
    assert menu.display_state.message == "menu message"


def test_input_cursor_remains_on_menu_above_status_and_padding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer()
    menu.enter_input_mode("Name: ", lambda text: None)
    menu.set_status_bar("READY")
    frame = renderer._compose_frame(40, 30)
    menu_lines = renderer._menu_renderer.render(max_width=38).splitlines()
    writes: list[str] = []
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    renderer._restore_cursor(frame)
    prompt_row = next(i + 1 for i, line in enumerate(menu_lines) if "Name:" in line)
    assert writes == [f"\033[{prompt_row};9H\033[?25h"]


def test_static_status_changes_and_resize_invalidate_render_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer()
    size = terminal_size((40, 20))
    writes: list[str] = []
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size", lambda: size
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    renderer.render()
    original = renderer._previous_lines
    menu_renderer = renderer._menu_renderer
    menu.set_status_bar("READY")
    renderer.render()
    assert renderer._previous_lines is not None
    assert renderer._previous_lines[-1] == "READY"
    writes.clear()
    renderer.render()
    assert writes == []
    menu.set_status_bar("CHANGED")
    renderer.render()
    assert writes
    size = terminal_size((12, 25))
    renderer.render()
    assert len(renderer._previous_lines) == 25
    assert renderer._previous_lines[-1] == "CHANGED"
    menu.clear_status_bar()
    size = terminal_size((40, 20))
    renderer.render()
    assert renderer._previous_lines == original
    assert renderer._menu_renderer is menu_renderer


def test_responsive_status_caches_until_width_or_explicit_refresh_changes() -> None:
    from tuiloom import StatusBar

    menu, renderer = make_renderer()
    calls: list[int] = []
    state = "RUNNING"

    def responsive(width: int) -> str:
        calls.append(width)
        return (
            f"{state} │ 42/80 │ 6/10"
            if width < 40
            else f"{state} │ Turn 42/80 │ 6/10 delivered"
        )

    menu.set_status_bar(StatusBar.responsive(responsive))
    assert renderer._compose_frame(50, 20)[-1].endswith("delivered")
    renderer._compose_frame(50, 25)
    assert calls == [50]
    state = "PAUSED"
    assert renderer._compose_frame(50, 25)[-1].startswith("RUNNING")
    menu.refresh_status_bar()
    assert renderer._compose_frame(50, 25)[-1].startswith("PAUSED")
    assert renderer._compose_frame(25, 25)[-1] == "PAUSED │ 42/80 │ 6/10"
    assert calls == [50, 50, 25]
    menu.set_status_bar(menu.status_bar)  # type: ignore[arg-type]
    renderer._compose_frame(25, 25)
    assert calls == [50, 50, 25, 25]


def test_dynamic_status_is_evaluated_before_render_cache_and_written_as_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tuiloom import StatusBar

    menu, renderer = make_renderer()
    state = "READY"
    menu.set_status_bar(StatusBar.dynamic(lambda: state))
    writes: list[str] = []
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((40, 20)),
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    renderer.render()
    writes.clear()
    renderer.render()
    assert writes == []
    state = "RUNNING"
    renderer.render()
    assert renderer._previous_lines is not None
    assert renderer._previous_lines[-1] == "RUNNING"
    assert "\033[20;2H" in "".join(writes)
    assert "\033[J" not in "".join(writes)


@pytest.mark.parametrize("kind", ["dynamic", "responsive"])
def test_status_producer_must_return_string(kind: str) -> None:
    from tuiloom import StatusBar

    menu, renderer = make_renderer()
    if kind == "dynamic":
        status = StatusBar.dynamic(lambda: 42)  # type: ignore[arg-type,return-value]
    else:
        status = StatusBar.responsive(lambda width: ["log"])  # type: ignore[arg-type,return-value]
    menu.set_status_bar(status)
    with pytest.raises(TypeError, match="str"):
        renderer._compose_frame(40, 20)


def test_empty_status_still_reserves_exactly_one_row() -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(ScreenContent.static("content"))
    renderer._compose_frame(40, 20)
    assert panel._runtime.viewport is not None
    previous_height = panel._runtime.viewport.height
    menu.set_status_bar("")
    frame = renderer._compose_frame(40, 20)
    assert len(frame) == 20
    assert frame[-1] == ""
    assert panel._runtime.viewport.height == previous_height - 1


@pytest.mark.parametrize("mode", ["smart", "strict"])
def test_status_resize_preserves_stream_follow_policy(mode: str) -> None:
    from typing import cast

    from tuiloom import AutoScrollMode

    menu, renderer = make_renderer()
    panel = menu.add_content_panel(
        ScreenContent.stream(iter(())), auto_scroll=cast(AutoScrollMode, mode)
    )
    panel._runtime.renderer.append_stream_batch(["\n".join(map(str, range(40)))])
    renderer._compose_frame(40, 20)
    renderer.apply_stream_auto_scroll(panel.auto_scroll, panel)
    renderer.scroll_panel(panel, "up")
    assert panel._runtime.viewport is not None
    offset = panel._runtime.viewport.offset_y
    menu.set_status_bar("RUNNING")
    panel._runtime.renderer.append_stream_batch(["\n40"])
    renderer.apply_stream_auto_scroll(panel.auto_scroll, panel)
    renderer._compose_frame(40, 20)
    if mode == "strict":
        assert panel._runtime.viewport.is_at_bottom()
    else:
        assert panel._runtime.viewport.offset_y == offset
        assert not panel._runtime.smart_auto_scroll_active


def test_status_reservation_updates_responsive_panel_effective_height() -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(ScreenContent.responsive(lambda size: "content"))
    renderer._compose_frame(40, 20)
    original = panel._runtime.effective_size
    assert original is not None
    menu.set_status_bar("READY")
    renderer._compose_frame(40, 20)
    assert panel._runtime.effective_size is not None
    assert panel._runtime.effective_size.width == original.width
    assert panel._runtime.effective_size.height == original.height - 1


def test_input_cursor_is_hidden_when_only_status_fits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer()
    menu.enter_input_mode("Name: ", lambda text: None)
    menu.set_status_bar("READY")
    frame = renderer._compose_frame(40, 1)
    writes: list[str] = []
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    renderer._restore_cursor(frame)
    assert frame == ["Terminal window is too small."]
    assert writes == ["\033[?25l"]
