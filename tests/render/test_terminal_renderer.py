from __future__ import annotations

from os import terminal_size

import pytest

from tuiloom import (
    ContentPanel,
    KeyBinding,
    MenuDisplay,
    ScreenContent,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.render.terminal_text import display_width
from tuiloom.task_exit import TaskExitState


def make_renderer(
    *,
    content: ScreenContent | str | None = "one\ntwo\nthree",
    spacing: bool = True,
) -> tuple[TerminalMenu, TerminalRenderer]:
    app = TerminalApp("App")
    configured = ScreenContent.static(content) if isinstance(content, str) else content
    menu = TerminalMenu(app, MenuDisplay("main", "Main"), content_spacing=spacing)
    if configured is not None:
        menu.add_content_panel(configured)
    menu.add_command("Run", lambda context: None)
    renderer = TerminalRenderer(
        menu=menu,
        menu_renderer=MenuRenderer(menu),
        content_spacing=spacing,
    )
    menu._terminal_renderer = renderer
    return menu, renderer


def compose_with_panel_rows(
    menu: TerminalMenu, renderer: TerminalRenderer, rows: int
) -> list[str]:
    menu_height = len(renderer._menu_renderer.render(max_width=28).splitlines())
    terminal_height = menu_height + 1 + 2 * len(menu.content_panels) + rows
    return renderer._compose_frame(30, terminal_height)


@pytest.mark.parametrize("width,height", [(2, 1), (1, 2), (0, 0), (8, 3)])
def test_too_small_fallback_without_status_fits_physical_bounds(
    width: int, height: int
) -> None:
    _, renderer = make_renderer()

    frame = renderer._compose_frame(width, height)

    assert len(frame) <= max(1, height)
    assert all(display_width(line) <= width for line in frame)


@pytest.mark.parametrize("panels", [False, True])
@pytest.mark.parametrize("status", [False, True])
def test_inline_input_cursor_tracks_prompt_before_footer(
    monkeypatch: pytest.MonkeyPatch, panels: bool, status: bool
) -> None:
    menu, renderer = make_renderer(content="content" if panels else None)
    menu.enter_input_mode("Value: ", lambda text: None)
    assert menu._input is not None
    menu._input.buffer = "a" * 30 + "界"
    menu.display_state.width = 16
    menu.display_state.strict_width = True
    menu.display_state.message = "Footer"
    if status:
        menu.set_status_bar("READY")
    frame = renderer._compose_frame(40, 30)
    prompt_row = next(index + 1 for index, line in enumerate(frame) if "界" in line)
    writes: list[str] = []
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)

    renderer._restore_cursor(frame)

    assert writes == [f"\033[{prompt_row};14H\033[?25h"]


def test_explicit_frame_result_carries_the_input_cursor() -> None:
    menu, renderer = make_renderer(content=None)
    menu.enter_input_mode("Name: ", lambda text: None)

    result = renderer.compose(40, 30)

    assert result.lines == renderer._compose_frame(40, 30)
    assert result.cursor is not None
    row, column = result.cursor
    assert "Name:" in result.lines[row - 1]
    assert column <= display_width(result.lines[row - 1])


@pytest.mark.parametrize(
    ("rows", "layouts", "expected"),
    [
        (11, [(1, 1, None)] * 3, [4, 4, 3]),
        (20, [(1, 4, None), (3, 4, None)], [4, 16]),
        (23, [(3, 1, None), (1, 1, 8)], [18, 5]),
        (12, [(1, 4, None), (1, 2, None)], [6, 6]),
        (20, [(1, 8, None), (3, 4, None)], [8, 12]),
        (100, [(9, 1, 85), (1, 20, None)], [80, 20]),
        (100, [(9, 1, 60), (1, 20, None)], [60, 40]),
        (20, [(10, 1, 3), (1, 1, None)], [3, 17]),
        (20, [(10, 1, 3), (2, 1, 5), (1, 1, None)], [3, 5, 12]),
        (20, [(1, 4, 4), (3, 2, None)], [4, 16]),
        (20, [(1, 2, 3), (3, 2, 5)], [3, 5]),
        (6, [(1, 4, 4), (3, 2, 2)], [4, 2]),
        (10, [(0.5, 1, None), (1.5, 1, None)], [2, 8]),
        (20, [(0.5, 1, None), (1.5, 1, None)], [4, 16]),
        (7, [(1, 1, None), (2, 1, None), (3, 1, None)], [1, 2, 4]),
        (11, [(1e308, 1, None)] * 3, [4, 4, 3]),
        (12, [(1e-308, 1, None), (1e308, 1, None)], [1, 11]),
        (12, [(10**400, 1, None), (10**400, 1, None)], [6, 6]),
    ],
)
def test_panel_rows_follow_weight_ratios_with_minimum_and_maximum_bounds(
    rows: int,
    layouts: list[tuple[float, int, int | None]],
    expected: list[int],
) -> None:
    menu, renderer = make_renderer(content=None)
    panels: list[ContentPanel] = []
    for height_weight, minimum, maximum in layouts:
        panels.append(
            menu.add_content_panel(
                ScreenContent.static("content"),
                height_weight=height_weight,
                min_height=minimum,
                max_height=maximum,
            )
        )

    frame = compose_with_panel_rows(menu, renderer, rows)

    assert [
        p._runtime.viewport.height if p._runtime.viewport else None for p in panels
    ] == expected
    menu_height = len(renderer._menu_renderer.render(max_width=28).splitlines())
    assert len(frame) == sum(expected) + 2 * len(panels) + 1 + menu_height


@pytest.mark.parametrize("spacing", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_weights_allocate_complete_panel_frames(spacing: bool, reverse: bool) -> None:
    menu, renderer = make_renderer(content=None, spacing=spacing)
    graph = menu.add_content_panel(ScreenContent.static("graph"), height_weight=3)
    simulation = menu.add_content_panel(
        ScreenContent.static("simulation"), height_weight=1, max_height=8
    )
    if reverse:
        menu.set_content_layout([[simulation], [graph]])
    menu_height = len(renderer._menu_renderer.render(max_width=28).splitlines())

    frame = renderer._compose_frame(30, menu_height + int(spacing) + 23)

    assert graph._runtime.viewport is not None and graph._runtime.viewport.height == 15
    assert (
        simulation._runtime.viewport is not None
        and simulation._runtime.viewport.height == 4
    )
    borders = [index for index, line in enumerate(frame) if line.startswith("╭")]
    heights = [borders[1], borders[2] - int(spacing) - borders[1]]
    assert heights == ([6, 17] if reverse else [17, 6])
    assert len(frame) == menu_height + int(spacing) + 23


def test_panel_minimums_that_do_not_fit_use_the_existing_too_small_frame() -> None:
    menu, renderer = make_renderer()
    first = menu.content_panels[0]
    first.set_layout(min_height=4)
    second = menu.add_content_panel(ScreenContent.static("second"), min_height=3)

    assert compose_with_panel_rows(menu, renderer, 6) == [
        "Terminal window is too small."
    ]
    assert first._runtime.viewport is None
    assert second._runtime.viewport is None
    assert compose_with_panel_rows(menu, renderer, 7)[0].startswith("╭")
    assert first._runtime.viewport is not None and first._runtime.viewport.height == 4
    assert second._runtime.viewport is not None and second._runtime.viewport.height == 3


@pytest.mark.parametrize(
    ("rows", "collapsed", "expected"),
    [
        (20, (True, False, False), [2, 5, 13]),
        (20, (False, True, False), [11, 2, 7]),
        (20, (True, True, True), [2, 2, 2]),
        (6, (True, True, True), [2, 2, 2]),
        (5, (True, True, True), None),
        (20, (False, False, False), [10, 4, 6]),
    ],
)
def test_collapsed_panels_reserve_fixed_rows_before_weighted_sharing(
    rows: int, collapsed: tuple[bool, ...], expected: list[int] | None
) -> None:
    menu, renderer = make_renderer(content=None)
    panels = [
        menu.add_content_panel(
            ScreenContent.static("content"),
            height_weight=height_weight,
            min_height=4,
            collapsed_height=2,
        )
        for height_weight in (3, 1, 2)
    ]
    for panel, state in zip(panels, collapsed, strict=True):
        if state:
            panel.collapse()
    frame = compose_with_panel_rows(menu, renderer, rows)
    if expected is None:
        assert frame == ["Terminal window is too small."]
        assert all(panel._runtime.viewport is None for panel in panels)
    else:
        assert [
            p._runtime.viewport.height if p._runtime.viewport else None for p in panels
        ] == expected
        menu_height = len(renderer._menu_renderer.render(max_width=28).splitlines())
        assert len(frame) == sum(expected) + 2 * len(panels) + 1 + menu_height


def test_expand_uses_current_terminal_size_and_updated_layout() -> None:
    menu, renderer = make_renderer()
    panel = menu.content_panels[0]
    panel.set_collapsed_height(5)
    panel.set_layout(min_height=2, max_height=3)
    panel.collapse()
    compose_with_panel_rows(menu, renderer, 10)
    viewport = panel._runtime.viewport
    assert viewport is not None and viewport.height == 5
    panel.set_layout(height_weight=2, min_height=4, max_height=8)
    compose_with_panel_rows(menu, renderer, 20)
    assert viewport.height == 5
    panel.expand()
    compose_with_panel_rows(menu, renderer, 6)
    assert panel._runtime.viewport is viewport and viewport.height == 6


@pytest.mark.parametrize("spacing", [False, True])
def test_collapse_before_first_render_can_recover_from_too_small_frame(
    spacing: bool,
) -> None:
    menu, renderer = make_renderer(spacing=spacing)
    panel = menu.content_panels[0]
    panel.set_layout(min_height=10)
    menu_height = len(renderer._menu_renderer.render(max_width=28).splitlines())
    terminal_height = menu_height + int(spacing) + 3
    assert renderer._compose_frame(30, terminal_height) == [
        "Terminal window is too small."
    ]
    panel.collapse()
    assert renderer._compose_frame(30, terminal_height)[0].startswith("╭")
    assert panel._runtime.viewport is not None and panel._runtime.viewport.height == 1
    panel.expand()
    assert renderer._compose_frame(30, terminal_height) == [
        "Terminal window is too small."
    ]


def test_live_collapse_keeps_focus_scroll_and_viewport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer(content="\n".join("x" * 50 for _ in range(30)))
    panel = menu.content_panels[0]
    other = menu.add_content_panel(ScreenContent.static("other"))
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((30, 30)),
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", lambda _: None)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    menu._focused_panel = panel
    renderer.render()
    viewport = panel._runtime.viewport
    assert viewport is not None
    viewport.offset_x, viewport.offset_y = 2, 5
    panel._runtime.smart_auto_scroll_active = False
    panel.collapse()
    renderer.render()
    assert panel._runtime.viewport is viewport and viewport.height == 1
    assert (viewport.offset_x, viewport.offset_y) == (2, 5)
    assert menu._focused_panel is panel and not panel._runtime.smart_auto_scroll_active
    menu._handle_event(InputEvent(binding=KeyBinding("down")))
    assert viewport.offset_y == 6
    assert other._runtime.viewport is not None and other._runtime.viewport.offset_y == 0
    panel.expand()
    renderer.render()
    assert panel._runtime.viewport is viewport and viewport.height > 1
    assert (viewport.offset_x, viewport.offset_y) == (2, 6)
    assert menu._focused_panel is panel


def test_live_layout_change_redraws_and_preserves_focus_and_scroll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer(content="\n".join("x" * 50 for _ in range(30)))
    first = menu.content_panels[0]
    second = menu.add_content_panel(ScreenContent.static("second"))
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((30, 30)),
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", lambda _: None)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    menu._focused_panel = first
    renderer.render()
    viewport = first._runtime.viewport
    assert viewport is not None
    viewport.offset_x = 2
    viewport.offset_y = 5

    first.set_layout(min_height=2, max_height=3)
    renderer.render()

    assert first._runtime.viewport is viewport
    assert viewport.height == 3
    assert (viewport.offset_x, viewport.offset_y) == (2, 5)
    assert menu._focused_panel is first
    menu._handle_event(InputEvent(binding=KeyBinding("down")))
    assert viewport.offset_y == 6
    assert (
        second._runtime.viewport is not None and second._runtime.viewport.offset_y == 0
    )

    first.set_layout(min_height=25, max_height=25)
    compose_with_panel_rows(menu, renderer, 30)
    assert first._runtime.viewport is viewport
    assert viewport.offset_y == 5  # Growing the viewport clamps to the new bottom.
    assert menu._focused_panel is first


@pytest.mark.parametrize("mode", ["strict", "smart"])
@pytest.mark.parametrize("collapse", [False, True])
def test_auto_scroll_uses_new_panel_height_and_keeps_smart_pause(
    mode: str, collapse: bool
) -> None:
    menu, renderer = make_renderer(content=ScreenContent.stream(iter(())))
    panel = menu.content_panels[0]
    panel.set_auto_scroll(mode)  # type: ignore[arg-type]
    menu.add_content_panel(ScreenContent.static("other"))
    panel._runtime.renderer.append_stream_batch(["\n".join(str(i) for i in range(30))])
    compose_with_panel_rows(menu, renderer, 12)
    viewport = panel._runtime.viewport
    assert viewport is not None
    renderer.apply_stream_auto_scroll(panel.auto_scroll, panel)
    renderer.scroll_panel(panel, "up")
    paused_offset = viewport.offset_y
    assert not panel._runtime.smart_auto_scroll_active

    if collapse:
        panel.set_collapsed_height(3)
        panel.collapse()
    else:
        panel.set_layout(max_height=3)
    assert not panel._runtime.smart_auto_scroll_active
    panel._runtime.renderer.append_stream_batch(["\nnext"])
    renderer.apply_stream_auto_scroll(panel.auto_scroll, panel)
    compose_with_panel_rows(menu, renderer, 12)

    assert panel._runtime.viewport is viewport
    assert viewport.height == 3
    if mode == "strict":
        assert viewport.is_at_bottom()
    else:
        assert viewport.offset_y == paused_offset
        assert not viewport.is_at_bottom()
        while not viewport.is_at_bottom():
            renderer.scroll_panel(panel, "down")
        assert panel._runtime.smart_auto_scroll_active
        panel._runtime.renderer.append_stream_batch(["\nlast"])
        renderer.apply_stream_auto_scroll(panel.auto_scroll, panel)
        compose_with_panel_rows(menu, renderer, 12)
        assert viewport.is_at_bottom()


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


@pytest.mark.parametrize("content", [None, "content"])
@pytest.mark.parametrize("strict", [False, True])
def test_menu_growth_is_bounded_without_lowering_requested_minimum(
    content: str | None, strict: bool
) -> None:
    menu, renderer = make_renderer(content=content)
    menu.display_state.width = 10
    menu.display_state.strict_width = strict
    menu.display_state.title = "x" * 50
    for terminal_width in (60, 25, 12, 25, 60):
        lines = renderer._compose_frame(terminal_width, 20)
        assert lines != ["Terminal window is too small."]
        expected = 12 if strict else min(52, terminal_width)
        assert display_width(lines[-1]) == expected
        assert all(display_width(line) <= terminal_width for line in lines)
        assert lines[-1].endswith("╯")
        assert "".join(lines).count("x") == 50
    assert renderer._compose_frame(11, 20) == ["Terminal wi"]


def test_strict_width_can_be_smaller_than_automatic_structural_minimum() -> None:
    menu, renderer = make_renderer(content=None)
    menu.display_state.width = 1
    menu.display_state.strict_width = True
    assert all(display_width(line) == 3 for line in renderer._compose_frame(3, 20))
    menu.display_state.strict_width = False
    assert renderer._compose_frame(5, 20) == ["Termi"]


def test_automatic_width_without_requested_minimum_is_bounded() -> None:
    menu, renderer = make_renderer(content=None)
    menu.display_state.title = "x" * 80
    lines = renderer._compose_frame(20, 20)
    assert all(display_width(line) == 20 for line in lines)


def test_short_menu_keeps_requested_width_in_large_terminal() -> None:
    menu, renderer = make_renderer(content=None)
    menu.display_state.width = 20
    lines = renderer._compose_frame(80, 20)
    assert all(display_width(line) == 22 for line in lines)


def test_reflow_increases_menu_height_and_reallocates_panel_space() -> None:
    menu, renderer = make_renderer()
    menu.display_state.width = 10
    menu.display_state.text = "alpha beta gamma delta epsilon"
    wide = renderer._compose_frame(40, 25)
    panel = menu.content_panels[0]
    assert panel._runtime.viewport is not None
    wide_panel_height = panel._runtime.viewport.height
    narrow = renderer._compose_frame(12, 25)
    assert panel._runtime.viewport.height < wide_panel_height
    for word in ("alpha", "beta", "gamma", "delta", "epsilon"):
        assert word in "\n".join(narrow)
    assert renderer._compose_frame(40, 25) == wide


def test_reflow_still_requires_enough_terminal_height() -> None:
    menu, renderer = make_renderer(content=None)
    menu.display_state.width = 10
    menu.display_state.text = "alpha beta gamma delta epsilon"
    assert renderer._compose_frame(40, 10) != ["Terminal window is too small."]
    assert renderer._compose_frame(12, 10) == ["Terminal win"]


def test_content_viewport_fills_available_inner_geometry() -> None:
    menu, renderer = make_renderer(content=ScreenContent.static("a\nb\nc\nd\ne"))
    panel = menu.content_panels[0]
    lines = renderer._compose_frame(20, 14)
    assert len(lines) == 14
    assert panel._runtime.viewport is not None
    assert panel._runtime.viewport.width == 18
    assert panel._runtime.viewport.height > 0


def test_multiple_panels_stack_with_labels_and_equal_inner_heights() -> None:
    menu, renderer = make_renderer(content=ScreenContent.static("first"))
    first = menu.content_panels[0]
    first.set_description("First")
    second = menu.add_content_panel(
        ScreenContent.static("second"), description="Second"
    )

    lines = renderer._compose_frame(32, 20)
    top_indices = [index for index, line in enumerate(lines) if line.startswith("╭")]
    bottom_indices = [index for index, line in enumerate(lines) if line.startswith("╰")]

    assert len(top_indices) == 3
    assert "First" in lines[top_indices[0]]
    assert "Second" in lines[top_indices[1]]
    first_height = bottom_indices[0] - top_indices[0]
    second_height = bottom_indices[1] - top_indices[1]
    assert first_height - second_height in (0, 1)
    assert first._runtime.viewport is not None
    assert second._runtime.viewport is not None


def test_multiple_panels_require_one_inner_row_each() -> None:
    menu, renderer = make_renderer(content=ScreenContent.static("first"))
    menu.add_content_panel(ScreenContent.static("second"), description="Second")
    assert renderer._compose_frame(30, 10) == ["Terminal window is too small."]


def test_scrolling_changes_only_the_target_panel_viewport() -> None:
    menu, renderer = make_renderer(
        content=ScreenContent.static("\n".join(str(index) for index in range(30)))
    )
    first = menu.content_panels[0]
    second = menu.add_content_panel(
        ScreenContent.static("\n".join(f"b{index}" for index in range(30))),
        description="Second",
    )
    renderer._compose_frame(24, 20)

    renderer.scroll_panel(first, "down")

    assert first._runtime.viewport is not None and first._runtime.viewport.offset_y == 1
    assert (
        second._runtime.viewport is not None and second._runtime.viewport.offset_y == 0
    )


@pytest.mark.parametrize("size", [(5, 5), (30, 2)])
def test_terminal_too_small_accounts_for_both_boxes(
    size: tuple[int, int],
) -> None:
    _, renderer = make_renderer()
    assert renderer._compose_frame(*size) == [
        "Terminal window is too small."[: size[0]]
    ]


def test_hidden_menu_preserves_content_frame() -> None:
    menu, renderer = make_renderer()
    menu.hide_menu()
    frame = renderer._compose_frame(30, 16)
    assert len(frame) == 16
    assert "one" in "\n".join(frame)
    assert "Main" not in "\n".join(frame)


def test_viewport_navigation_and_smart_auto_scroll() -> None:
    menu, renderer = make_renderer(
        content=ScreenContent.static("\n".join(str(i) for i in range(30)))
    )
    panel = menu.content_panels[0]
    renderer._compose_frame(20, 14)
    assert panel._runtime.viewport is not None
    renderer.apply_stream_auto_scroll("smart", panel)
    renderer._compose_frame(20, 14)
    bottom = panel._runtime.viewport.offset_y
    assert bottom > 0
    renderer.scroll_panel(panel, "up")
    assert panel._runtime.viewport.offset_y == bottom - 1
    renderer.apply_stream_auto_scroll("smart", panel)
    renderer._compose_frame(20, 14)
    assert panel._runtime.viewport.offset_y == bottom - 1
    renderer.scroll_panel(panel, "down")
    assert panel._runtime.viewport.is_at_bottom()


def test_horizontal_navigation_and_source_replacement() -> None:
    menu, renderer = make_renderer(content=ScreenContent.static("x" * 60))
    panel = menu.content_panels[0]
    renderer._compose_frame(20, 14)
    renderer.scroll_panel(panel, "right")
    assert panel._runtime.viewport is not None
    assert panel._runtime.viewport.offset_x == 1
    renderer.scroll_panel(panel, "left")
    assert panel._runtime.viewport.offset_x == 0
    panel.set_content(ScreenContent.static("new"))
    assert panel._runtime.viewport is None


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
    menu.display_state.message = "Changed"
    renderer.render()
    assert writes
    renderer.invalidate()
    assert renderer._previous_lines is None


def test_render_cache_tracks_resize_and_live_width_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer(content=None)
    menu.display_state.width = 10
    menu.display_state.title = "x" * 50
    writes: list[str] = []
    size = terminal_size((30, 20))
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size", lambda: size
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)

    renderer.render()
    assert renderer._previous_lines is not None
    assert display_width(renderer._previous_lines[-1]) == 30
    writes.clear()
    renderer.render()
    assert writes == []

    menu.display_state.strict_width = True
    renderer.render()
    assert display_width(renderer._previous_lines[-1]) == 12
    assert writes and not any("\x1b[H\x1b[J" in write for write in writes)
    assert any("X" in write for write in writes)  # Erase the old right edge.

    menu.display_state.width = 15
    renderer.render()
    assert display_width(renderer._previous_lines[-1]) == 17
    menu.display_state.strict_width = False
    renderer.render()
    assert display_width(renderer._previous_lines[-1]) == 30

    for columns in (17, 16, 60):
        writes.clear()
        size = terminal_size((columns, 20))
        renderer.render()
        assert any("\x1b[H\x1b[J" in write for write in writes)
        if columns == 16:
            assert renderer._previous_lines == ["Terminal window "]
        else:
            assert display_width(renderer._previous_lines[-1]) == min(52, columns)


def test_wait_animation_changes_the_cached_terminal_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer(content=ScreenContent.static("working"))
    panel = menu.content_panels[0]
    menu._task_exit = TaskExitState(
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
    menu, renderer = make_renderer(content=ScreenContent.static("first"))
    first = menu.content_panels[0]
    second = menu.add_content_panel(ScreenContent.static("second"))
    active = [first]
    menu._task_exit = TaskExitState(
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
