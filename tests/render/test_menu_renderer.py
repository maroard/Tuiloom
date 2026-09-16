from typing import cast

import pytest

from tuiloom import ScreenContent, ScreenContext, TerminalApp, TerminalMenu
from tuiloom.event_loop.event_loop import EventLoop
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_text import display_width, visual_cells
from tuiloom.task_exit import TaskExitView


def make_renderer(
    *,
    content: str | None = "content",
    width: int | None = None,
    app_name: str = "Application",
) -> tuple[TerminalMenu, MenuRenderer]:
    app = TerminalApp(app_name)
    context = ScreenContext("main", "Title", width=width, text="Description")
    configured = ScreenContent.static(content) if content is not None else None
    menu = TerminalMenu(app, context, content=configured)
    menu.add_command("First", lambda command: None)
    menu.add_command("界 command", lambda command: None)
    return menu, MenuRenderer(menu)


def test_menu_render_uses_name_title_text_and_selected_indicator() -> None:
    menu, renderer = make_renderer()
    rendered = renderer.render()
    assert "Application" in rendered
    assert "Title" in rendered
    assert "Description" in rendered
    assert "> First" in rendered
    assert "  界 command" in rendered
    assert "  Back" in rendered
    assert "Choice?" not in rendered
    assert all(
        display_width(line) == renderer.width + 2 for line in rendered.splitlines()
    )
    assert menu._selected_index == 0


def test_menu_border_reflects_focus_and_single_zone_is_solid() -> None:
    menu, renderer = make_renderer()
    assert "─" in renderer.render()
    menu._focused_panel = menu.content_panels[0]
    renderer.update()
    assert "┄" in renderer.render()

    single, single_renderer = make_renderer(content=None)
    single._focused_panel = None
    single_renderer.update()
    assert "─" in single_renderer.render()
    assert "┄" not in single_renderer.render()


def test_exit_view_treats_a_retiring_panel_as_focusable_content() -> None:
    menu, renderer = make_renderer()
    panel = menu.content_panels[0]
    panel.remove()

    class Loop:
        active_panels = (panel,)

    menu._event_loop = cast(EventLoop, Loop())
    menu._task_exit = TaskExitView(
        mode="choice",
        selected_index=0,
        previous_focus=None,
        previous_selected_index=0,
        wait_started_at=0.0,
        visible_panels=(panel,),
    )
    menu._focused_panel = panel

    renderer.update()

    assert renderer.render().startswith("╭┄")


def test_disabled_command_stays_visible_but_selection_skips_it() -> None:
    menu, renderer = make_renderer()
    first = menu.commands[0]
    menu.disable_command(first)
    renderer.update()
    rendered = renderer.render()
    assert "First (disabled)" in rendered
    assert "> 界 command" in rendered


def test_width_is_a_minimum_and_expands_for_long_metadata() -> None:
    menu, renderer = make_renderer(width=4)
    assert renderer.width >= display_width("Application")
    menu.set_command_label(menu.commands[0], "A very long command label")
    renderer.update()
    assert renderer.width >= display_width("> A very long command label")


def test_alert_replaces_body_without_false_prompt() -> None:
    menu, renderer = make_renderer()
    menu.show_alert("Warning")
    renderer.update()
    rendered = renderer.render()
    assert "Warning" in rendered
    assert "First" not in rendered
    assert "Press Enter" not in rendered

    menu.show_alert("Confirm", on_confirm=lambda context: None)
    renderer.update()
    rendered = renderer.render()
    assert "Press Enter to continue" in rendered
    assert "─" in rendered


def test_input_prompt_and_grapheme_mask_are_inside_menu_box() -> None:
    menu, renderer = make_renderer()
    menu.enter_input_mode("Password: ", lambda value: None, hidden=True)
    menu._input_buffer = "e\u0301👨‍👩‍👧"
    renderer.update()
    rendered = renderer.render()
    assert "Password: **" in rendered
    assert "e\u0301" not in rendered


def test_messages_and_hidden_menu_renders_nothing() -> None:
    menu, renderer = make_renderer(width=10)
    menu.screen_context.message = "A footer message that wraps"
    renderer.update()
    assert "footer" in renderer.render()
    menu.show = False
    renderer.update()
    assert renderer.render() == ""


def test_disabled_suffix_is_included_in_natural_width() -> None:
    menu, renderer = make_renderer()
    menu.disable_command(menu.commands[1])
    lines = renderer.render().splitlines()
    assert "界 command (disabled)" in "\n".join(lines)
    assert all(display_width(line) == renderer.width + 2 for line in lines)


@pytest.mark.parametrize("width", [1, 2, 4, 12, 40])
def test_strict_width_is_exact_and_changes_live(width: int) -> None:
    menu, renderer = make_renderer(width=width)
    menu.screen_context.strict_width = True
    lines = renderer.render().splitlines()
    assert all(display_width(line) == width + 2 for line in lines)
    menu.screen_context.strict_width = False
    expanded = renderer.render()
    assert display_width(expanded.splitlines()[0]) >= 15
    menu.screen_context.strict_width = True
    menu.screen_context.width = width + 1
    assert display_width(renderer.render().splitlines()[0]) == width + 3


def test_strict_width_without_width_keeps_automatic_sizing() -> None:
    menu, renderer = make_renderer()
    automatic = renderer.render()
    menu.screen_context.strict_width = True
    assert renderer.render() == automatic
    menu.screen_context.width = 4
    assert display_width(renderer.render().splitlines()[0]) == 6
    menu.screen_context.width = None
    assert renderer.render() == automatic


def test_render_limit_is_cached_separately_from_unbounded_render() -> None:
    _, renderer = make_renderer(width=4)
    unbounded = renderer.render()
    clipped = renderer.render(max_width=8)
    assert clipped != unbounded
    assert all(display_width(line) == 10 for line in clipped.splitlines())
    assert renderer.render(max_width=8) == clipped
    assert renderer.render() == unbounded


def test_wrap_keeps_all_text_explicit_lines_and_styles() -> None:
    lines = MenuRenderer._text_rows(
        "\x1b[31m界e\u0301👨‍👩‍👧abcdef\n\nSecond long line\x1b[0m", 8, "│"
    )
    plain = [
        "".join(cell.text for cell in visual_cells(line) if cell.offset == 0)
        for line in lines
    ]
    assert "".join(line[1:-1].replace(" ", "") for line in plain) == (
        "界e\u0301👨‍👩‍👧abcdefSecondlongline"
    )
    assert "│        │" in plain
    assert all(
        "\x1b[31m" in line
        for line, raw in zip(lines, plain, strict=True)
        if raw.strip("│ ")
    )
    assert all(
        "\x1b[0m" in line
        for line, raw in zip(lines, plain, strict=True)
        if raw.strip("│ ")
    )
    assert all(display_width(line) == 10 for line in lines)


@pytest.mark.parametrize(
    "field", ["title", "text", "message", "app", "command", "exit", "alert", "input"]
)
def test_every_menu_element_wraps_without_losing_text(field: str) -> None:
    long_text = "abcdefghij" * 10
    menu, renderer = make_renderer(
        width=8, app_name=long_text if field == "app" else "Application"
    )
    menu.screen_context.strict_width = True
    if field in {"title", "text", "message"}:
        setattr(menu.screen_context, field, long_text)
    elif field == "command":
        menu.set_command_label(menu.commands[0], long_text)
    elif field == "exit":
        menu._exit_label = long_text
    elif field == "alert":
        menu.show_alert(long_text, on_confirm=lambda context: None)
    elif field == "input":
        menu.enter_input_mode("Prompt: ", lambda value: None)
        menu._input_buffer = long_text
    lines = renderer.render().splitlines()
    assert all(display_width(line) == 10 for line in lines)
    assert all(line.endswith(("│", "╮", "┤", "╯")) for line in lines)
    assert long_text in "".join(line[1:-1].strip() for line in lines)
    assert len(lines) > 15
    if field == "input":
        assert menu._input_buffer == long_text


def test_wrapped_command_continuations_align_and_keep_one_selection_marker() -> None:
    menu, renderer = make_renderer(content=None, width=12)
    menu.screen_context.strict_width = True
    menu.set_command_label(menu.commands[0], "alpha beta gamma")
    lines = renderer.render().splitlines()
    start = lines.index("│> alpha beta│")
    assert lines[start + 1] == "│  gamma     │"
    assert sum(">" in line for line in lines) == 1
    assert menu._selected_index == 0


def test_wrapped_disabled_command_keeps_its_complete_suffix() -> None:
    menu, renderer = make_renderer(content=None, width=12)
    menu.screen_context.strict_width = True
    menu.disable_command(menu.commands[0])
    lines = renderer.render().splitlines()
    assert "│  (disabled)│" in lines


def test_wrap_prefers_word_boundaries_and_preserves_explicit_short_lines() -> None:
    assert MenuRenderer._text_rows("alpha beta gamma\nend", 12, "│") == [
        "│ alpha beta │",
        "│ gamma      │",
        "│ end        │",
    ]


@pytest.mark.parametrize("width", [1, 2, 3])
@pytest.mark.parametrize("label", ["a", "abc", "界a", "\x1b[31mabc\x1b[0m"])
def test_narrow_command_geometry_does_not_depend_on_selection(
    width: int, label: str
) -> None:
    selected = MenuRenderer._command_rows(label, ">", width, "│")
    unselected = MenuRenderer._command_rows(label, " ", width, "│")
    assert len(selected) == len(unselected)
    assert selected[1:] == unselected[1:]
    assert selected[0].replace(">", " ", 1) == unselected[0]
