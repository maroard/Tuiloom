from tuiloom import ScreenContext, TerminalApp, TerminalMenu
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_text import display_width


def make_renderer(
    *, content: str | None = "content", width: int | None = None
) -> tuple[TerminalMenu, MenuRenderer]:
    app = TerminalApp("Application")
    context = ScreenContext("main", "Title", width=width, text="Description")
    menu = TerminalMenu(app, context, content_source=content)
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


def test_messages_wrap_and_hidden_menu_renders_nothing() -> None:
    menu, renderer = make_renderer(width=10)
    menu.screen_context.message = "A footer message that wraps"
    renderer.update()
    assert "footer" in renderer.render()
    menu.show = False
    renderer.update()
    assert renderer.render() == ""
