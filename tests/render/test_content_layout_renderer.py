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
