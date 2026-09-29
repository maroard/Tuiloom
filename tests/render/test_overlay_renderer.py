from __future__ import annotations

from os import terminal_size

import pytest

from tuiloom import (
    ChoiceOption,
    KeyBinding,
    MenuDisplay,
    ScreenContent,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.segment_diff import get_segment_changes
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.render.terminal_text import clip_display, display_width, visual_cells


def make_renderer(*, overlay: bool = True) -> tuple[TerminalMenu, TerminalRenderer]:
    menu = TerminalMenu(
        TerminalApp("App"),
        MenuDisplay("main", "Main", width=16),
        presentation="overlay" if overlay else "inline",
    )
    menu.add_command("Run", lambda context: None)
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=MenuRenderer(menu), content_spacing=True
    )
    menu._terminal_renderer = renderer
    return menu, renderer


def styled_cells(line: str) -> list[tuple[str, int, int, str]]:
    # These cases use full SGR resets and foreground colors. Ignore historical
    # sequences before the last reset when comparing effective cell styles.
    return [
        (cell.text, cell.offset, cell.width, cell.style.rsplit("\033[0m", 1)[-1])
        for cell in visual_cells(line)
    ]


@pytest.mark.parametrize("has_panels", [False, True])
@pytest.mark.parametrize("status", [False, True])
def test_overlay_is_centered_in_the_body(has_panels: bool, status: bool) -> None:
    menu, renderer = make_renderer()
    if has_panels:
        menu.add_content_panel(ScreenContent.static("background"))
    if status:
        menu.set_status_bar("READY")
    frame = renderer._compose_frame(40, 24)
    box = menu._menu_renderer or renderer._menu_renderer
    menu_lines = box.render(max_width=38).splitlines()
    x = (40 - display_width(menu_lines[0])) // 2
    y = (24 - int(status) - len(menu_lines)) // 2
    assert len(frame) == 24
    for row, line in enumerate(menu_lines):
        assert clip_display(frame[y + row], x, x + display_width(line)) == line
    if status:
        assert frame[-1] == "READY"


@pytest.mark.parametrize("spacing", [False, True])
@pytest.mark.parametrize("status", [False, True])
@pytest.mark.parametrize("collapsed", [False, True])
def test_overlay_has_no_effect_on_panel_geometry(
    spacing: bool, status: bool, collapsed: bool
) -> None:
    menu, renderer = make_renderer()
    renderer._content_spacing = spacing
    first = menu.add_content_panel(
        ScreenContent.responsive(lambda size: "graph"), weight=3
    )
    second = menu.add_content_panel(ScreenContent.static("logs"), weight=1)
    if collapsed:
        second.collapse()
    if status:
        menu.set_status_bar("READY")
    renderer._compose_frame(40, 24)
    assert first._runtime.viewport is not None and second._runtime.viewport is not None
    assert (
        first._runtime.viewport.height + second._runtime.viewport.height + 4
        == 24 - int(status)
    )
    if collapsed:
        assert second._runtime.viewport.height == 1
    size = first._runtime.effective_size
    viewports = (first._runtime.viewport, second._runtime.viewport)
    menu.hide_menu()
    background = renderer._compose_frame(40, 24)
    assert first._runtime.effective_size == size
    assert viewports == (first._runtime.viewport, second._runtime.viewport)
    menu.show_menu()
    renderer._compose_frame(40, 24)
    assert first._runtime.effective_size == size
    assert "graph" not in "\n".join(background)  # Responsive producer runs in a worker.


def test_hidden_inline_releases_menu_height_and_keeps_status() -> None:
    menu, renderer = make_renderer(overlay=False)
    panel = menu.add_content_panel(ScreenContent.static("content"))
    menu.set_status_bar("READY")
    renderer._compose_frame(40, 24)
    assert panel._runtime.viewport is not None
    old_height = panel._runtime.viewport.height
    menu_height = len(renderer._menu_renderer.render().splitlines())
    menu.hide_menu()
    frame = renderer._compose_frame(40, 24)
    assert panel._runtime.viewport.height == old_height + menu_height + 1
    assert frame[-1] == "READY" and "Main" not in "\n".join(frame)


def test_inline_default_retains_exact_legacy_frame() -> None:
    app = TerminalApp("App")
    default = TerminalMenu(app, MenuDisplay("main", "Main", width=16))
    explicit, explicit_renderer = make_renderer(overlay=False)
    for menu in (default, explicit):
        menu.add_content_panel(ScreenContent.static("one\ntwo\nthree"))
    default.add_command("Run", lambda context: None)
    default_renderer = TerminalRenderer(
        menu=default, menu_renderer=MenuRenderer(default), content_spacing=True
    )
    assert default_renderer._compose_frame(40, 24) == explicit_renderer._compose_frame(
        40, 24
    )
    assert default.content_panels[0]._runtime.viewport is not None
    assert default.content_panels[0]._runtime.viewport.height == 13


@pytest.mark.parametrize(
    "text", ["界" * 40, "👩‍💻" * 40, "e\u0301" * 80, "\033[31m" + "界" * 40 + "\033[0m"]
)
def test_composition_preserves_unicode_ansi_and_background_edges(text: str) -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(ScreenContent.static("\n".join([text] * 40)))
    menu._focused_panel = panel  # Keep focus borders equal in both frames.
    menu.display_state.title = "\033[32m界 e\u0301 👩‍💻\033[0m"
    visible = renderer._compose_frame(41, 24)
    menu.hide_menu()
    hidden = renderer._compose_frame(41, 24)
    menu_lines = renderer._menu_renderer  # Showing restores the menu's exact box.
    menu.show_menu()
    box = menu_lines.render(max_width=39).splitlines()
    x = (41 - display_width(box[0])) // 2
    y = (24 - len(box)) // 2
    for row, line in enumerate(visible):
        assert display_width(line) == 41
        if y <= row < y + len(box):
            assert styled_cells(clip_display(line, 0, x)) == styled_cells(
                clip_display(hidden[row], 0, x)
            )
            assert styled_cells(clip_display(line, x + 18, 41)) == styled_cells(
                clip_display(hidden[row], x + 18, 41)
            )
        else:
            assert line == hidden[row]
    assert panel._runtime.viewport is not None and panel._runtime.viewport.height == 22
    assert "\033[32m" in "\n".join(visible)


def test_resize_wrapping_and_choices_do_not_reduce_panel_height() -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(ScreenContent.static("graph"))
    menu.display_state.title = "a" * 50
    menu.add_choice(
        "Mode", [ChoiceOption("界"), ChoiceOption("Option B")], lambda context: None
    )
    menu._handle_event(InputEvent(KeyBinding("down")))
    for width in (60, 30, 18, 30, 60):
        frame = renderer._compose_frame(width, 40)
        assert frame != ["Terminal window is too small."]
        assert len(frame) == 40
        assert all(display_width(line) <= width for line in frame)
        assert (
            panel._runtime.viewport is not None and panel._runtime.viewport.height == 38
        )
    menu.display_state.strict_width = True
    assert renderer._compose_frame(17, 40) == ["Terminal window i"]
    assert renderer._compose_frame(18, 40) != ["Terminal window is too small."]


def test_too_small_and_hidden_overlay_with_a_large_alert() -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(ScreenContent.static("graph"))
    menu.show_alert("\n".join(["alert"] * 30))
    assert renderer._compose_frame(40, 24) == ["Terminal window is too small."]
    menu.hide_menu()
    assert len(renderer._compose_frame(40, 24)) == 24
    assert panel._runtime.viewport is not None and panel._runtime.viewport.height == 22
    menu.show_menu()
    menu.set_status_bar("READY")
    frame = renderer._compose_frame(40, 24)
    assert frame[0] == "Terminal window is too small." and frame[-1] == "READY"
    assert len(frame) == 24


def test_all_collapsed_panels_still_center_in_full_body() -> None:
    menu, renderer = make_renderer()
    for label in ("Graph", "Logs"):
        menu.add_content_panel(
            ScreenContent.static(label), description=label
        ).collapse()
    frame = renderer._compose_frame(40, 30)
    box = renderer._menu_renderer.render().splitlines()
    x = (40 - display_width(box[0])) // 2
    y = (30 - len(box)) // 2
    assert clip_display(frame[y], x, x + 18) == box[0]
    assert all(
        p._runtime.viewport is not None and p._runtime.viewport.height == 1
        for p in menu.content_panels
    )


def test_overlay_and_panels_use_existing_focus_borders() -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(ScreenContent.static("graph"))
    frame = renderer._compose_frame(40, 24)
    assert frame[0].startswith("╭┄")
    assert "╭────────────────╮" in "\n".join(frame)
    menu._handle_event(InputEvent(KeyBinding("tab")))
    frame = renderer._compose_frame(40, 24)
    assert frame[0].startswith("╭─")
    assert "╭┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄╮" in "\n".join(frame)
    assert menu._focused_panel is panel
    menu.show_alert("Alert")
    menu.hide_menu()
    assert renderer._compose_frame(40, 24)[0].startswith("╭─")


def test_menu_visibility_preserves_overlay_content_and_status() -> None:
    menu, renderer = make_renderer()
    menu.add_content_panel(ScreenContent.static("graph"))
    menu.set_status_bar("READY")
    menu.hide_menu()
    frame = renderer._compose_frame(40, 24)
    assert "graph" in "\n".join(frame)
    assert frame[-1] == "READY"
    menu.show_menu()
    assert renderer._compose_frame(40, 24)[-1] == "READY"


@pytest.mark.parametrize("status", [False, True])
def test_overlay_input_cursor_is_inside_the_composited_prompt(
    monkeypatch: pytest.MonkeyPatch, status: bool
) -> None:
    menu, renderer = make_renderer()
    menu.add_content_panel(ScreenContent.static("graph"))
    menu.enter_input_mode("Name: ", lambda text: None)
    menu._handle_event(InputEvent(None, "界"))
    if status:
        menu.set_status_bar("READY")
    frame = renderer._compose_frame(40, 24)
    prompt_row = next(i for i, line in enumerate(frame) if "Name: " in line)
    writes: list[str] = []
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    renderer._restore_cursor(frame)
    x = (40 - 18) // 2
    assert writes == [f"\033[{prompt_row + 1};{x + 3 + 8}H\033[?25h"]
    menu.hide_menu()
    frame = renderer._compose_frame(40, 24)
    writes.clear()
    renderer._restore_cursor(frame)
    assert writes == ["\033[?25l"]
    menu.show_menu()
    frame = renderer._compose_frame(10, 5)
    writes.clear()
    renderer._restore_cursor(frame)
    assert writes == ["\033[?25l"]


def test_overlay_close_and_open_use_diff_and_restore_updated_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(ScreenContent.dynamic(lambda: ""))
    panel._runtime.renderer.replace_dynamic_content("\n".join(["old" * 14] * 30))
    size = terminal_size((40, 24))
    writes: list[str] = []
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size", lambda: size
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    renderer.render()
    assert renderer._previous_lines is not None
    visible = renderer._previous_lines
    panel._runtime.renderer.replace_dynamic_content("\n".join(["new" * 14] * 30))
    renderer.render()
    writes.clear()
    menu.hide_menu()
    renderer.render()
    hidden = renderer._previous_lines
    assert hidden is not None and hidden != visible
    assert all("new" in line for line in hidden[1:-1])
    assert "\033[H\033[J" not in "".join(writes)
    assert get_segment_changes(visible, hidden)
    writes.clear()
    renderer.render()
    assert writes == []
    menu.show_menu()
    renderer.render()
    assert "\033[H\033[J" not in "".join(writes)
    writes.clear()
    size = terminal_size((30, 28))
    renderer.render()
    assert "\033[H\033[J" in "".join(writes)


@pytest.mark.parametrize("width", [40, 41, 42])
def test_segment_changes_restore_wide_graphemes_at_both_overlay_edges(
    width: int,
) -> None:
    menu, renderer = make_renderer()
    menu.add_content_panel(ScreenContent.static("\n".join(["界" * 30] * 30)))
    visible = renderer._compose_frame(width, 24)
    menu.hide_menu()
    hidden = renderer._compose_frame(width, 24)
    # Verify every changed span begins/ends on complete current graphemes.
    for change in get_segment_changes(visible, hidden):
        start = change.column - 1
        cells = visual_cells(hidden[change.row - 1])
        if start < len(cells):
            assert cells[start].offset == 0
        end = start + display_width(change.content)
        if end < len(cells):
            assert cells[end].offset == 0


def test_closing_a_menu_without_panels_erases_the_previous_box(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer()
    writes: list[str] = []
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((40, 24)),
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    renderer.render()
    writes.clear()
    menu.hide_menu()
    renderer.render()
    assert renderer._previous_lines == [""] * 24
    assert "X" in "".join(writes) and "\033[J" not in "".join(writes)


def test_wrapped_input_cursor_tracks_last_prompt_row_before_footer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer()
    menu.enter_input_mode("Value: ", lambda text: None)
    menu._handle_event(InputEvent(None, "a" * 30 + "界"))
    menu.display_state.message = "Footer"
    menu.display_state.strict_width = True
    frame = renderer._compose_frame(40, 30)
    box = renderer._menu_renderer.render().splitlines()
    input_end = next(i for i, line in enumerate(box) if "界" in line)
    x, y = (40 - 18) // 2, (30 - len(box)) // 2
    writes: list[str] = []
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    renderer._restore_cursor(frame)
    # Input is wrapped into 14 inner text columns: remaining text is 11 cells.
    assert writes == [f"\033[{y + input_end + 1};{x + 3 + 11}H\033[?25h"]


def test_visible_overlay_input_keeps_legacy_priority_with_stored_panel_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(ScreenContent.static("\n".join(map(str, range(40)))))
    menu.enter_input_mode("Value: ", lambda text: None)
    menu._focused_panel = panel
    frame = renderer._compose_frame(40, 24)
    menu._handle_event(InputEvent(KeyBinding("down")))
    assert panel._runtime.viewport is not None and panel._runtime.viewport.offset_y == 0
    assert menu._display_input_buffer() == ""
    writes: list[str] = []
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    renderer._restore_cursor(frame)
    assert writes[0].endswith("\033[?25h")


@pytest.mark.parametrize("overlay", [False, True])
def test_hidden_box_does_not_push_status_out_of_a_one_row_terminal(
    overlay: bool,
) -> None:
    menu, renderer = make_renderer(overlay=overlay)
    menu.hide_menu()
    menu.set_status_bar("READY")
    assert renderer._compose_frame(40, 1) == ["READY"]


@pytest.mark.parametrize(
    "buffer,column", [("", 21), ("a", 22), ("a   ", 25), ("界  ", 25)]
)
def test_overlay_input_cursor_counts_trailing_spaces(
    monkeypatch: pytest.MonkeyPatch, buffer: str, column: int
) -> None:
    menu, renderer = make_renderer()
    menu.enter_input_mode("Value: ", lambda text: None)
    menu._handle_event(InputEvent(None, buffer))
    frame = renderer._compose_frame(40, 30)
    prompt_row = next(i + 1 for i, line in enumerate(frame) if "Value:" in line)
    writes: list[str] = []
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    renderer._restore_cursor(frame)
    assert writes == [f"\033[{prompt_row};{column}H\033[?25h"]


def test_application_toggle_shortcut_keeps_segment_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu, renderer = make_renderer()
    menu.add_content_panel(ScreenContent.static("\n".join(["background"] * 30)))
    menu.app.add_global_command(
        KeyBinding("m"), "Toggle menu", lambda context: context.menu.toggle_menu()
    )
    writes: list[str] = []
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((40, 24)),
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    renderer.render()
    for _ in range(2):
        writes.clear()
        menu._handle_event(InputEvent(KeyBinding("m"), "m"))
        renderer.render()
        assert writes and "\033[J" not in "".join(writes)
