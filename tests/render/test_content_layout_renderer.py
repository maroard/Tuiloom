from __future__ import annotations

from os import terminal_size

import pytest

from tuiloom import MenuDisplay, ScreenContent, TerminalApp, TerminalMenu
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.render.terminal_text import display_width


def make_renderer(*, overlay: bool = False) -> tuple[TerminalMenu, TerminalRenderer]:
    menu = TerminalMenu(
        TerminalApp("App"),
        MenuDisplay("main", "Main", width=12),
        presentation="overlay" if overlay else "inline",
    )
    menu.add_command("Run", lambda context: None)
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=MenuRenderer(menu), content_spacing=True
    )
    menu._terminal_renderer = renderer
    return menu, renderer


def test_two_columns_above_one_full_width_panel() -> None:
    menu, renderer = make_renderer()
    a = menu.add_content_panel(ScreenContent.static("alpha"), description="A")
    b = menu.add_content_panel(ScreenContent.static("beta"), description="B")
    c = menu.add_content_panel(ScreenContent.static("gamma"), description="C")
    menu.set_content_layout([[a, b], [c]])

    frame = renderer._compose_frame(40, 24)

    assert frame[0].count("╭") == 2
    assert "A" in frame[0] and "B" in frame[0]
    assert a._runtime.viewport is not None and a._runtime.viewport.width == 18
    assert b._runtime.viewport is not None and b._runtime.viewport.width == 18
    assert c._runtime.viewport is not None and c._runtime.viewport.width == 38
    assert a._runtime.viewport.height == b._runtime.viewport.height
    assert display_width(frame[0]) == 40
    assert any(line.startswith("╭") and line.count("╭") == 1 for line in frame[1:])


def test_explicit_singleton_rows_match_legacy_frame_exactly() -> None:
    menu, renderer = make_renderer()
    a = menu.add_content_panel(ScreenContent.static("alpha"))
    b = menu.add_content_panel(ScreenContent.static("beta"))
    legacy = renderer._compose_frame(40, 24)

    menu.set_content_layout([[a], [b]])

    assert renderer._compose_frame(40, 24) == legacy


def test_three_columns_split_remainder_without_gaps() -> None:
    menu, renderer = make_renderer()
    panels = [
        menu.add_content_panel(ScreenContent.static(str(i)), description=str(i))
        for i in range(3)
    ]
    menu.set_content_layout([panels])

    frame = renderer._compose_frame(41, 20)

    assert frame[0].count("╭") == 3
    assert display_width(frame[0]) == 41
    assert [
        panel._runtime.viewport.width for panel in panels if panel._runtime.viewport
    ] == [12, 12, 11]


def test_width_weights_split_complete_frames_three_to_one() -> None:
    menu, renderer = make_renderer(overlay=True)
    a = menu.add_content_panel(ScreenContent.static("A"), width_weight=3)
    b = menu.add_content_panel(ScreenContent.static("B"), width_weight=1)
    menu.set_content_layout([[a, b]])
    menu.hide_menu()

    frame = renderer._compose_frame(80, 20)

    assert frame[0].count("╭") == 2
    assert display_width(frame[0]) == 80
    assert a._runtime.viewport is not None and a._runtime.viewport.width == 58
    assert b._runtime.viewport is not None and b._runtime.viewport.width == 18
    assert a._runtime.viewport.height == b._runtime.viewport.height == 18


def test_extreme_width_weight_keeps_each_panel_viewport_positive() -> None:
    menu, renderer = make_renderer(overlay=True)
    a = menu.add_content_panel(ScreenContent.static("A"), width_weight=100)
    b = menu.add_content_panel(ScreenContent.static("B"), width_weight=1)
    menu.set_content_layout([[a, b]])
    menu.hide_menu()

    frame = renderer._compose_frame(7, 8)

    assert display_width(frame[0]) == 7
    assert a._runtime.viewport is not None and a._runtime.viewport.width == 2
    assert b._runtime.viewport is not None and b._runtime.viewport.width == 1


def test_rows_use_mean_weight_and_shared_vertical_bounds() -> None:
    menu, renderer = make_renderer(overlay=True)
    a = menu.add_content_panel(ScreenContent.static("a"), height_weight=3)
    b = menu.add_content_panel(ScreenContent.static("b"), height_weight=1)
    c = menu.add_content_panel(ScreenContent.static("c"), height_weight=1)
    menu.set_content_layout([[a, b], [c]])

    renderer._compose_frame(40, 24)

    assert a._runtime.viewport is not None
    assert b._runtime.viewport is not None
    assert c._runtime.viewport is not None
    assert (a._runtime.viewport.height, b._runtime.viewport.height) == (14, 14)
    assert c._runtime.viewport.height == 6


def test_row_collapse_status_and_overlay_keep_geometry_independent() -> None:
    menu, renderer = make_renderer(overlay=True)
    a = menu.add_content_panel(ScreenContent.static("a"))
    b = menu.add_content_panel(ScreenContent.static("b"))
    c = menu.add_content_panel(ScreenContent.static("c"))
    menu.set_content_layout([[a, b], [c]])
    menu.set_status_bar("READY")
    menu.content_layout[0].collapse()

    frame = renderer._compose_frame(40, 20)

    assert a._runtime.viewport is not None and a._runtime.viewport.height == 1
    assert b._runtime.viewport is not None and b._runtime.viewport.height == 1
    assert c._runtime.viewport is not None and c._runtime.viewport.height == 14
    assert frame[-1] == "READY"


def test_too_narrow_or_short_never_creates_zero_sized_viewport() -> None:
    menu, renderer = make_renderer(overlay=True)
    panels = [menu.add_content_panel(ScreenContent.static(str(i))) for i in range(3)]
    menu.set_content_layout([panels])

    menu.hide_menu()
    assert renderer._compose_frame(8, 20) == ["Terminal"]
    assert all(panel._runtime.viewport is None for panel in panels)
    renderer._compose_frame(9, 20)
    assert all(panel._runtime.viewport is not None for panel in panels)
    assert all(
        panel._runtime.viewport.width == 1
        for panel in panels
        if panel._runtime.viewport
    )
    menu.show_menu()
    assert renderer._compose_frame(9, 3) == ["Terminal "]
    assert all(
        panel._runtime.viewport is not None
        and panel._runtime.viewport.width > 0
        and panel._runtime.viewport.height > 0
        for panel in panels
    )


def test_unicode_and_sgr_do_not_bleed_across_column_border() -> None:
    menu, renderer = make_renderer(overlay=True)
    a = menu.add_content_panel(ScreenContent.static("\033[31m界\033[0m"))
    b = menu.add_content_panel(ScreenContent.static("👩‍💻 e\u0301"))
    menu.set_content_layout([[a, b]])
    menu.hide_menu()

    frame = renderer._compose_frame(21, 6)

    assert display_width(frame[1]) == 21
    assert "界" in frame[1] and "👩‍💻" in frame[1]
    assert "\033[0m" in frame[1]
    assert frame[1].count("┊") + frame[1].count("│") == 4


def test_arrow_scrolling_targets_only_the_focused_column() -> None:
    menu, renderer = make_renderer(overlay=True)
    content = "\n".join("x" * 60 for _ in range(60))
    a = menu.add_content_panel(ScreenContent.static(content))
    b = menu.add_content_panel(ScreenContent.static(content))
    menu.set_content_layout([[a, b]])
    menu.hide_menu()
    renderer._compose_frame(30, 12)

    menu._scroll_content("down")
    menu._scroll_content("right")

    assert a._runtime.viewport is not None
    assert b._runtime.viewport is not None
    assert (a._runtime.viewport.offset_y, a._runtime.viewport.offset_x) == (1, 1)
    assert (b._runtime.viewport.offset_y, b._runtime.viewport.offset_x) == (0, 0)


def test_layout_change_uses_segment_diff_at_unchanged_terminal_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer()
    a = menu.add_content_panel(ScreenContent.static("界" * 20))
    b = menu.add_content_panel(ScreenContent.static("\033[31mB\033[0m"))
    writes: list[str] = []
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((40, 24)),
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    renderer.render()
    writes.clear()

    menu.set_content_layout([[a, b]])
    renderer.render()

    assert writes
    assert "\033[H\033[J" not in "".join(writes)
    assert renderer._previous_lines is not None
    assert renderer._previous_lines[0].count("╭") == 2


def test_vertical_span_draws_one_tall_frame_beside_two_stacked_frames() -> None:
    menu, renderer = make_renderer(overlay=True)
    graph = menu.add_content_panel(
        ScreenContent.static("graph"),
        description="Graph",
        width_weight=3,
        height_weight=100,
    )
    output = menu.add_content_panel(
        ScreenContent.static("output"), description="Output", height_weight=3
    )
    info = menu.add_content_panel(
        ScreenContent.static("info"), description="Info", height_weight=1
    )
    menu.set_content_layout([[graph, output], [graph, info]])
    menu.hide_menu()

    frame = renderer._compose_frame(40, 20)

    assert len(frame) == 20
    assert all(display_width(row) == 40 for row in frame)
    assert sum(row.count("╭") for row in frame) == 3
    assert sum(row.count("╰") for row in frame) == 3
    assert graph._runtime.viewport is not None
    assert output._runtime.viewport is not None
    assert info._runtime.viewport is not None
    assert graph._runtime.viewport.width == 28
    assert output._runtime.viewport.width == info._runtime.viewport.width == 8
    assert graph._runtime.viewport.height == 18
    assert output._runtime.viewport.height > info._runtime.viewport.height
    info_top = next(index for index, row in enumerate(frame) if "Info" in row)
    assert frame[0].index("╭", 1) == frame[info_top].index("╭")
    assert frame[info_top].startswith("│")


def test_vertical_span_keeps_viewport_and_selection_on_resize() -> None:
    from tuiloom import SelectableItem

    menu, renderer = make_renderer(overlay=True)
    graph = menu.add_content_panel(
        ScreenContent.selectable([SelectableItem(str(i), key=i) for i in range(40)]),
        selection_style="reverse",
    )
    output = menu.add_content_panel(ScreenContent.static("output"))
    info = menu.add_content_panel(ScreenContent.static("info"))
    menu.set_content_layout([[graph, output], [graph, info]])
    menu.hide_menu()

    renderer._compose_frame(40, 12)
    viewport = graph._runtime.viewport
    assert viewport is not None
    graph.select_item(30)
    renderer._compose_frame(40, 12)
    assert graph.selected_index == 30
    assert viewport.offset_y > 0
    old_offset = viewport.offset_y

    renderer._compose_frame(50, 15)
    assert graph._runtime.viewport is viewport
    assert graph.selected_index == 30
    assert viewport.offset_y <= old_offset
    assert viewport.offset_y <= 30 < viewport.offset_y + viewport.height
    renderer.scroll_panel(graph, "right")
    assert viewport.offset_x == 0  # short selectable rows need no horizontal scroll


def test_vertical_span_too_small_terminal_does_not_create_viewports() -> None:
    menu, renderer = make_renderer(overlay=True)
    graph = menu.add_content_panel(ScreenContent.static("graph"))
    output = menu.add_content_panel(ScreenContent.static("output"))
    info = menu.add_content_panel(ScreenContent.static("info"))
    menu.set_content_layout([[graph, output], [graph, info]])
    menu.hide_menu()

    assert renderer._compose_frame(5, 5) == ["Termi"]
    assert all(panel._runtime.viewport is None for panel in (graph, output, info))


def test_spanning_panel_height_weight_controls_block_share() -> None:
    menu, renderer = make_renderer(overlay=True)
    graph = menu.add_content_panel(ScreenContent.static("graph"))
    output = menu.add_content_panel(ScreenContent.static("output"))
    info = menu.add_content_panel(ScreenContent.static("info"))
    footer = menu.add_content_panel(ScreenContent.static("footer"))
    menu.set_content_layout([[graph, output], [graph, info], [footer]])
    menu.hide_menu()
    renderer._compose_frame(40, 30)
    assert graph._runtime.viewport is not None
    first_height = graph._runtime.viewport.height

    graph.update_layout(height_weight=100)
    renderer._compose_frame(40, 30)

    assert graph._runtime.viewport.height > first_height
    assert footer._runtime.viewport is not None
    assert footer._runtime.viewport.height >= footer.min_height
