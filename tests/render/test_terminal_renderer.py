from __future__ import annotations

from os import terminal_size

import pytest

from tuiloom import ScreenContext, TerminalApp, TerminalMenu
from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.task_exit import TaskExitView


def make_renderer(
    *, content: str | None = "one\ntwo\nthree", spacing: bool = True
) -> tuple[TerminalMenu, TerminalRenderer]:
    app = TerminalApp("App")
    menu = TerminalMenu(
        app,
        ScreenContext("main", "Main"),
        content_source=content,
        content_spacing=spacing,
    )
    menu.add_command("Run", lambda context: None)
    renderer = TerminalRenderer(
        menu=menu,
        menu_renderer=MenuRenderer(menu),
        content_renderer=ContentRenderer(content if content is not None else ""),
        content_spacing=spacing,
    )
    menu._terminal_renderer = renderer
    return menu, renderer


def test_composes_two_boxes_with_focus_and_optional_spacing() -> None:
    menu, renderer = make_renderer(spacing=True)
    lines = renderer._compose_frame(30, 16)
    assert lines[0].startswith("╭┄")
    assert any(line.startswith("╭─") for line in lines)
    assert "" in lines
    menu._focused_panel = menu.content_panels[0]
    lines = renderer._compose_frame(30, 16)
    assert lines[0].startswith("╭─")
    assert any(line.startswith("╭┄") for line in lines[2:])

    _, no_spacing = make_renderer(spacing=False)
    assert "" not in no_spacing._compose_frame(30, 16)


def test_no_content_omits_content_box_and_spacing() -> None:
    _, renderer = make_renderer(content=None)
    lines = renderer._compose_frame(30, 16)
    assert sum(line.startswith("╭") for line in lines) == 1
    assert "one" not in "\n".join(lines)


def test_content_viewport_fills_available_inner_geometry() -> None:
    _, renderer = make_renderer(content="a\nb\nc\nd\ne")
    lines = renderer._compose_frame(20, 14)
    assert len(lines) == 14
    assert renderer.viewport is not None
    assert renderer.viewport.width == 18
    assert renderer.viewport.height > 0


def test_multiple_panels_stack_with_labels_and_equal_inner_heights() -> None:
    menu, renderer = make_renderer(content="first")
    first = menu.content_panels[0]
    first.set_description("First")
    second = menu.add_content_panel("second", description="Second")

    lines = renderer._compose_frame(32, 20)
    top_indices = [index for index, line in enumerate(lines) if line.startswith("╭")]
    bottom_indices = [index for index, line in enumerate(lines) if line.startswith("╰")]

    assert len(top_indices) == 3
    assert "First" in lines[top_indices[0]]
    assert "Second" in lines[top_indices[1]]
    first_height = bottom_indices[0] - top_indices[0]
    second_height = bottom_indices[1] - top_indices[1]
    assert first_height - second_height in (0, 1)
    assert first._viewport is not None
    assert second._viewport is not None


def test_multiple_panels_require_one_inner_row_each() -> None:
    menu, renderer = make_renderer(content="first")
    menu.add_content_panel("second", description="Second")
    assert renderer._compose_frame(30, 10) == ["Terminal window is too small."]


def test_scrolling_changes_only_the_target_panel_viewport() -> None:
    menu, renderer = make_renderer(content="\n".join(str(index) for index in range(30)))
    first = menu.content_panels[0]
    second = menu.add_content_panel(
        "\n".join(f"b{index}" for index in range(30)),
        description="Second",
    )
    renderer._compose_frame(24, 20)

    renderer.scroll_panel(first, "down")

    assert first._viewport is not None and first._viewport.offset_y == 1
    assert second._viewport is not None and second._viewport.offset_y == 0


@pytest.mark.parametrize("size", [(5, 5), (30, 2)])
def test_terminal_too_small_accounts_for_both_boxes(
    size: tuple[int, int],
) -> None:
    _, renderer = make_renderer()
    assert renderer._compose_frame(*size) == ["Terminal window is too small."]


def test_hidden_menu_clears_complete_frame() -> None:
    menu, renderer = make_renderer()
    menu.show = False
    assert renderer._compose_frame(30, 16) == [""]


def test_viewport_navigation_and_smart_auto_scroll() -> None:
    _, renderer = make_renderer(content="\n".join(str(i) for i in range(30)))
    renderer._compose_frame(20, 14)
    assert renderer.viewport is not None
    renderer.apply_stream_auto_scroll("smart")
    renderer._compose_frame(20, 14)
    bottom = renderer.viewport.offset_y
    assert bottom > 0
    renderer.scroll_up()
    assert renderer.viewport.offset_y == bottom - 1
    renderer.apply_stream_auto_scroll("smart")
    renderer._compose_frame(20, 14)
    assert renderer.viewport.offset_y == bottom - 1
    renderer.scroll_down()
    assert renderer.viewport.is_at_bottom()


def test_horizontal_navigation_and_source_replacement() -> None:
    _, renderer = make_renderer(content="x" * 60)
    renderer._compose_frame(20, 14)
    renderer.scroll_right()
    assert renderer.viewport is not None
    assert renderer.viewport.offset_x == 1
    renderer.scroll_left()
    assert renderer.viewport.offset_x == 0
    renderer.set_content_renderer(ContentRenderer("new"))
    assert renderer.viewport is None


def test_render_writes_full_then_differential_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer()
    writes: list[str] = []
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((30, 16)),
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    renderer.render()
    assert any("\x1b[H\x1b[J" in write for write in writes)
    writes.clear()
    menu.screen_context.message = "Changed"
    renderer.render()
    assert writes
    renderer.invalidate()
    assert renderer._previous_lines is None


def test_wait_animation_changes_the_cached_terminal_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer(content="working")
    panel = menu.content_panels[0]
    menu._task_exit = TaskExitView(
        mode="waiting",
        selected_index=0,
        previous_focus=None,
        previous_selected_index=0,
        wait_started_at=0.0,
        visible_panels=(panel,),
        wait_phase=1,
    )
    monkeypatch.setattr(
        TerminalMenu,
        "_current_exit_panels",
        lambda self: (panel,),
    )
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((30, 16)),
    )
    writes: list[str] = []
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)

    renderer.render()
    writes.clear()
    menu._task_exit.wait_phase = 2
    renderer.render()

    assert writes
    assert "." in "".join(writes)


def test_same_count_operation_swap_changes_the_cached_terminal_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer(content="first")
    first = menu.content_panels[0]
    second = menu.add_content_panel("second")
    active = [first]
    menu._task_exit = TaskExitView(
        mode="choice",
        selected_index=0,
        previous_focus=None,
        previous_selected_index=0,
        wait_started_at=0.0,
        visible_panels=(first,),
    )
    monkeypatch.setattr(
        TerminalMenu,
        "_current_exit_panels",
        lambda self: tuple(active),
    )
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((30, 16)),
    )
    writes: list[str] = []
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)

    renderer.render()
    writes.clear()
    active[0] = second
    renderer.render()

    assert writes
