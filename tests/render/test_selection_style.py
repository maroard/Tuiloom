from __future__ import annotations

from tuiloom import (
    KeyBinding,
    MenuDisplay,
    ScreenContent,
    SelectableItem,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.segment_diff import get_segment_changes
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.render.terminal_text import display_width, reverse_display, visual_cells


def test_reverse_menu_fills_wrapped_rows_and_survives_resets() -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(
        app,
        MenuDisplay("main", "Main", width=12, strict_width=True),
        selection_style="reverse",
    )
    menu.add_command("\x1b[31mRed\x1b[0m long label 界", lambda context: None)
    rendered = MenuRenderer(menu).render().splitlines()
    highlighted = [row for row in rendered if "Red" in row or "label" in row]
    assert len(highlighted) >= 2
    for row in highlighted:
        cells = visual_cells(row)
        assert display_width(row) == 14
        assert all("\x1b[7m" in cell.style for cell in cells[1:-1])
    assert ">" not in "".join(highlighted)


def test_reverse_panel_fills_viewport_and_runtime_switch_redraws() -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(app, MenuDisplay("main", "Main"))
    panel = menu.add_content_panel(
        ScreenContent.selectable([SelectableItem("\x1b[32mGreen\x1b[0m 界")]),
        selection_style="reverse",
    )
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=MenuRenderer(menu), content_spacing=True
    )
    before = renderer._compose_frame(28, 16)
    line = next(row for row in before if "Green" in row)
    assert all("\x1b[7m" in cell.style for cell in visual_cells(line)[1:-1])
    panel.set_selection_style("marker")
    after = renderer._compose_frame(28, 16)
    assert any(
        "> Green"
        in "".join(cell.text for cell in visual_cells(row) if cell.offset == 0)
        for row in after
    )
    assert get_segment_changes(before, after)


def test_reverse_reasserts_after_embedded_sgr_reset_and_off() -> None:
    result = reverse_display("\x1b[31mred\x1b[0m plain\x1b[27m end", 20)
    assert "\x1b[0m\x1b[7m plain" in result
    assert "\x1b[27m\x1b[7m end" in result
    assert result.endswith("\x1b[0m")
    assert display_width(result) == 20


def test_horizontal_clip_keeps_reverse_across_visible_panel_width() -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(app, MenuDisplay("main", "Main"))
    panel = menu.add_content_panel(
        ScreenContent.selectable([SelectableItem("0123456789界abcdefghij")]),
        selection_style="reverse",
    )
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=MenuRenderer(menu), content_spacing=True
    )
    renderer._compose_frame(12, 16)
    viewport = panel._runtime.viewport
    assert viewport is not None
    viewport.scroll_right()
    frame = renderer._compose_frame(12, 16)
    highlighted = next(row for row in frame if "0123" in row)
    assert all("\x1b[7m" in cell.style for cell in visual_cells(highlighted)[1:-1])


def test_menu_style_can_change_at_runtime() -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(app, MenuDisplay("main", "Main"))
    menu.add_command("Run", lambda context: None)
    renderer = MenuRenderer(menu)
    assert "> Run" in renderer.render()
    menu.set_selection_style("reverse")
    assert "> Run" not in renderer.render()
    assert "\x1b[7m" in next(
        row for row in renderer.render().splitlines() if "Run" in row
    )


def test_selection_navigation_preserves_diff_baseline() -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(app, MenuDisplay("main", "Main"))
    panel = menu.add_content_panel(
        ScreenContent.selectable([SelectableItem("A"), SelectableItem("B")])
    )
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=MenuRenderer(menu), content_spacing=True
    )
    menu._terminal_renderer = renderer
    renderer._previous_lines = renderer._compose_frame(30, 18)
    menu._focused_panel = panel
    menu._handle_event(InputEvent(KeyBinding("down")))
    assert renderer._previous_lines is not None
