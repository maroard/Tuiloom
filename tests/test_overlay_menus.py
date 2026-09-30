from __future__ import annotations

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
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.task_exit import TaskExitState


def make_menu(app: TerminalApp | None = None) -> TerminalMenu:
    return TerminalMenu(
        app or TerminalApp("App"),
        MenuDisplay("main", "Main"),
        presentation="overlay",
    )


def press(menu: TerminalMenu, key: str, text: str | None = None) -> None:
    menu._handle_event(InputEvent(KeyBinding(key), text))


def test_presentation_defaults_and_explicit_modes() -> None:
    app = TerminalApp("App")
    assert TerminalMenu(app, MenuDisplay("root", "Root")).presentation == "inline"
    assert make_menu(app).presentation == "overlay"
    assert (
        TerminalMenu(
            app, MenuDisplay("root", "Root"), presentation="inline"
        ).presentation
        == "inline"
    )


@pytest.mark.parametrize("value", ["window", "", True, 1, []])
def test_invalid_presentation_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="presentation"):
        TerminalMenu(
            TerminalApp("App"),
            MenuDisplay("root", "Root"),
            presentation=value,  # type: ignore[arg-type]
        )


def test_navigation_inherits_and_explicit_inline_overrides() -> None:
    root = make_menu()
    app = root.app
    child = TerminalMenu(app, MenuDisplay("child", "Child"))
    explicit = TerminalMenu(app, MenuDisplay("inline", "Inline"), presentation="inline")
    app.push_menu(root)
    app.push_menu(child)
    assert child.presentation == "overlay"
    app.push_menu(explicit)
    assert explicit.presentation == "inline"
    app.pop_menu()
    assert app._menu_stack[-1] is child and child.presentation == "overlay"
    replacement = TerminalMenu(app, MenuDisplay("new", "New"))
    app.replace_menu(replacement)
    assert replacement.presentation == "overlay"
    app.reset_to(root)
    assert root.presentation == "overlay" and app._menu_stack == [root]
    app.reset_to(child)
    assert str(child.presentation) == "inline"  # A new root has no parent.
    app.replace_menu(root)
    app.push_menu(child)
    assert child.presentation == "overlay"  # Resolve again on reopening.


def test_reopening_under_an_inline_parent_resolves_inheritance_again() -> None:
    root = make_menu()
    app = root.app
    child = TerminalMenu(app, MenuDisplay("child", "Child"))
    app.push_menu(root)
    app.push_menu(child)
    app.pop_menu()
    app.reset_to(TerminalMenu(app, MenuDisplay("inline", "Inline")))
    app.push_menu(child)
    assert child.presentation == "inline"


def test_hide_show_toggle_focus_and_selection_without_stopping() -> None:
    menu = make_menu()
    first = menu.add_content_panel(ScreenContent.static("one"))
    second = menu.add_content_panel(ScreenContent.static("two"))
    menu.add_command("Run", lambda context: None)
    menu._running = True
    menu._selected_index = 1
    menu.hide_menu()
    assert not menu.menu_visible and menu._running
    assert menu._focused_panel is first
    press(menu, "tab")
    assert menu._focused_panel is second
    press(menu, "tab")
    assert menu._focused_panel is first
    menu.hide_menu()  # Idempotent, preserving the focused panel.
    assert menu._focused_panel is first
    menu.toggle_menu()
    assert menu.menu_visible and menu._focused_panel is None
    assert menu._selected_index == 1
    press(menu, "tab")
    menu.show_menu()  # Already visible: preserve normal panel focus.
    assert menu._focused_panel is first
    menu.toggle_menu()
    assert not menu.menu_visible and menu._focused_panel is first


def test_hidden_focus_normalizes_after_panel_add_and_remove() -> None:
    menu = make_menu()
    menu.hide_menu()
    calls: list[str] = []
    menu.add_command("Run", lambda context: calls.append("local"))
    menu.app.add_global_command(
        KeyBinding("g"), "Global", lambda context: calls.append("global")
    )
    press(menu, "enter")
    press(menu, "g", "g")
    assert calls == ["global"]
    first = menu.add_content_panel(ScreenContent.static("one"))
    second = menu.add_content_panel(ScreenContent.static("two"))
    assert menu._focused_panel is first
    second.remove()
    assert menu._focused_panel is first
    first.remove()
    assert menu._focused_panel is None
    press(menu, "enter")
    assert calls == ["global"]


def test_hidden_last_panel_removal_selects_a_visible_panel() -> None:
    menu = make_menu()
    first = menu.add_content_panel(ScreenContent.static("one"))
    last = menu.add_content_panel(ScreenContent.static("two"))
    menu._focused_panel = last
    menu.hide_menu()
    last.remove()
    assert menu._focused_panel is first


def test_hidden_alert_and_input_are_suspended_with_globals_available() -> None:
    menu = make_menu()
    menu.add_content_panel(ScreenContent.static("content"))
    submitted: list[str] = []
    calls: list[str] = []
    menu.app.add_global_command(
        KeyBinding("g"), "Global", lambda context: calls.append("global")
    )
    menu.enter_input_mode("Value: ", submitted.append)
    press(menu, "a", "a")
    menu.hide_menu()
    press(menu, "g", "g")
    press(menu, "enter")
    press(menu, "b", "b")
    assert calls == ["global"] and submitted == []
    assert menu._input is not None
    assert menu._input.buffer == "a"
    menu.show_alert("Confirm", on_confirm=lambda context: calls.append("alert"))
    press(menu, "enter")
    assert calls == ["global"]
    menu.show_menu()
    press(menu, "enter")
    assert calls == ["global", "alert"]
    press(menu, "enter")
    assert submitted == ["a"]


def test_overlay_commands_and_choices_use_existing_navigation() -> None:
    menu = make_menu()
    calls: list[int] = []
    menu.add_command("Run", lambda context: calls.append(42))
    choice = menu.add_choice(
        "Mode",
        [ChoiceOption("A"), ChoiceOption("B")],
        lambda context: calls.append(context.index),
    )
    press(menu, "enter")
    press(menu, "down")
    press(menu, "right")
    press(menu, "right")
    press(menu, "enter")
    assert calls == [42, 1] and choice.selected_index == 1
    menu.hide_menu()
    press(menu, "enter")
    assert calls == [42, 1]


def test_hidden_panels_remain_scrollable_with_a_suspended_alert() -> None:
    menu = make_menu()
    panel = menu.add_content_panel(ScreenContent.static("\n".join(map(str, range(80)))))
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=MenuRenderer(menu), content_spacing=True
    )
    menu._terminal_renderer = renderer
    menu.show_alert("Blocking")
    menu.hide_menu()
    renderer._compose_frame(40, 20)
    menu._handle_event(InputEvent(KeyBinding("down", ctrl=True)))
    assert panel._runtime.viewport is not None and panel._runtime.viewport.offset_y == 1
    menu.show_menu()
    press(menu, "down")
    assert menu._alert is not None
    assert panel._runtime.viewport.offset_y == 1 and menu._alert.text == "Blocking"


def test_task_exit_temporarily_shows_a_hidden_menu() -> None:
    menu = make_menu()
    panel = menu.add_content_panel(ScreenContent.static("working"))
    menu.hide_menu()
    menu._task_exit = TaskExitState(
        mode="choice",
        selected_index=0,
        previous_focus=panel,
        previous_selected_index=0,
        wait_started_at=0,
        visible_panels=(panel,),
    )
    menu._focused_panel = None
    assert MenuRenderer(menu).render()
    assert not menu.menu_visible
    press(menu, "escape")
    assert menu._task_exit is None and not menu.menu_visible
    assert menu._focused_panel is panel


def test_navigation_to_hidden_submenu_focuses_its_panel() -> None:
    root = make_menu()
    child = TerminalMenu(root.app, MenuDisplay("child", "Child"))
    panel = child.add_content_panel(ScreenContent.static("content"))
    child.hide_menu()
    root.app.push_menu(root)
    root.app.push_menu(child)
    assert child.presentation == "overlay"
    assert not child.menu_visible and child._focused_panel is panel
