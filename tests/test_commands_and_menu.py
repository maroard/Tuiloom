from __future__ import annotations

import pytest

from tuiloom import (
    CommandContext,
    KeyBinding,
    ScreenContext,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.render.menu_renderer import MenuRenderer


def make_menu(*, content: str | None = None) -> tuple[TerminalApp, TerminalMenu]:
    app = TerminalApp("App")
    menu = TerminalMenu(app, ScreenContext("main", "Main"), content_source=content)
    return app, menu


def press(menu: TerminalMenu, key: str, text: str | None = None) -> None:
    menu._handle_event(InputEvent(KeyBinding(key), text))


def test_menu_command_handles_support_all_mutations_and_stable_identity() -> None:
    _, menu = make_menu()
    calls: list[str] = []
    first = menu.add_command("First", lambda context: calls.append("first"))
    second = menu.add_command("Second", lambda context: calls.append("second"))

    menu.set_command_label(first, "Renamed")
    menu.set_command_behavior(first, lambda context: calls.append("new"))
    menu.move_command(first, 1)
    assert menu.commands == (second, first)
    assert first.label == "Renamed"
    assert first.position == 1

    menu.disable_command(second)
    assert not second.enabled
    menu.enable_command(second)
    assert second.enabled

    menu._selected_index = first.position
    press(menu, "enter")
    assert calls == ["new"]


@pytest.mark.parametrize("position", [-1, 2, True])
def test_add_command_rejects_invalid_positions(position: object) -> None:
    _, menu = make_menu()
    with pytest.raises((TypeError, ValueError)):
        menu.add_command(
            "Bad",
            lambda context: None,
            position=position,  # type: ignore[arg-type]
        )
    assert menu.commands == ()


def test_foreign_handles_and_submenus_are_rejected_immediately() -> None:
    _, menu = make_menu()
    foreign_app, foreign = make_menu()
    handle = foreign.add_command("Foreign", lambda context: None)
    with pytest.raises(ValueError, match="same TerminalApp"):
        menu.add_menu(foreign, "Foreign")
    with pytest.raises(ValueError, match="does not belong"):
        menu.set_command_label(handle, "No")
    with pytest.raises(ValueError, match="belong"):
        foreign_app.set_main_menu(menu)


def test_add_menu_pushes_submenu_without_recursive_run_and_main_labels() -> None:
    app, parent = make_menu()
    child = TerminalMenu(app, ScreenContext("child", "Child"))
    app.push_menu(parent)
    child.run = lambda: pytest.fail("submenu.run must not be called")  # type: ignore[method-assign]
    command = parent.add_menu(child, "Open")
    command.behavior(CommandContext(app, parent, command, KeyBinding("enter")))
    assert app._menu_stack == [parent, child]

    app.set_main_menu(parent)
    assert parent._exit_label == "Quit"
    app.set_main_menu(child)
    assert parent._exit_label == "Back"
    assert child._exit_label == "Quit"


def test_back_and_quit_follow_stack_depth_and_explicit_label_wins() -> None:
    app, root = make_menu()
    child = TerminalMenu(app, ScreenContext("child", "Child"))
    app.push_menu(root)
    app._running = True
    root.stop()
    assert not app._running

    app._running = True
    app.push_menu(child)
    child.set_exit_label("Return")
    assert MenuRenderer(child).render().count("Return") == 1
    child.stop()
    assert app._running
    assert app._menu_stack == [root]


def test_terminal_menu_run_is_deprecated_non_recursive_push() -> None:
    app, root = make_menu()
    child = TerminalMenu(app, ScreenContext("child", "Child"))
    app.push_menu(root)
    app._running = True

    with pytest.warns(DeprecationWarning):
        child.run()

    assert app._menu_stack == [root, child]


def test_selection_wraps_skips_disabled_and_exit_is_always_last() -> None:
    _, menu = make_menu()
    first = menu.add_command("First", lambda context: None)
    second = menu.add_command("Second", lambda context: None)
    menu.disable_command(second)
    assert menu._selected_index == 0
    press(menu, "up")
    assert menu._selected_index == len(menu.commands)
    press(menu, "down")
    assert menu._selected_index == first.position


def test_focus_navigation_routes_arrows_only_to_focused_zone() -> None:
    _, menu = make_menu(content="long content")
    menu.add_command("One", lambda context: None)
    press(menu, "tab")
    assert menu._focused_panel is menu.content_panels[0]
    press(menu, "tab")
    assert menu._focused_panel is None

    _, no_content = make_menu()
    press(no_content, "tab")
    assert no_content._focused_panel is None


def test_global_commands_are_immediate_invisible_and_locally_configurable() -> None:
    app, menu = make_menu()
    calls: list[str] = []
    command = app.add_global_command(
        KeyBinding("x"), "Execute", lambda context: calls.append("app")
    )
    assert app.global_commands == (command,)
    assert menu.commands == ()
    press(menu, "x", "x")
    assert calls == ["app"]

    menu.set_global_command_behavior(command, lambda context: calls.append("menu"))
    press(menu, "x", "x")
    assert calls[-1] == "menu"
    menu.disable_global_command(command)
    press(menu, "x", "x")
    assert calls == ["app", "menu"]
    menu.enable_global_command(command)
    menu.clear_global_command_behavior(command)
    press(menu, "x", "x")
    assert calls[-1] == "app"


def test_global_handle_metadata_mutations_and_ownership() -> None:
    app, _ = make_menu()
    other = TerminalApp("Other")

    def first(context: CommandContext) -> None:
        pass

    def second(context: CommandContext) -> None:
        pass

    command = app.add_global_command(KeyBinding("x"), "Old", first)
    app.set_global_command_binding(command, KeyBinding("y", alt=True))
    app.set_global_command_label(command, "New")
    app.set_global_command_behavior(command, second)
    assert command.binding == KeyBinding("y", alt=True)
    assert command.label == "New"
    assert command.behavior is second
    with pytest.raises(ValueError):
        other.set_global_command_label(command, "Foreign")


def test_context_contains_handle_and_triggering_binding() -> None:
    app, menu = make_menu()
    contexts: list[CommandContext] = []
    command = menu.add_command("Capture", contexts.append)
    press(menu, "enter")
    assert len(contexts) == 1
    assert contexts[0] == CommandContext(app, menu, command, KeyBinding("enter"))


def test_delete_command_invalidates_handle_and_preserves_other_selection() -> None:
    _, menu = make_menu()
    first = menu.add_command("First", lambda context: None)
    second = menu.add_command("Second", lambda context: None)
    third = menu.add_command("Third", lambda context: None)
    menu._selected_index = second.position

    menu.delete_command(first)

    assert menu.commands == (second, third)
    assert menu._selected_index == second.position
    for mutation in (
        lambda: menu.set_command_label(first, "No"),
        lambda: menu.set_command_behavior(first, lambda context: None),
        lambda: menu.move_command(first, 0),
        lambda: menu.disable_command(first),
        lambda: menu.enable_command(first),
        lambda: menu.delete_command(first),
        lambda: first.position,
    ):
        with pytest.raises(ValueError):
            mutation()


def test_deleting_selected_command_prefers_next_then_previous_then_exit() -> None:
    _, menu = make_menu()
    first = menu.add_command("First", lambda context: None)
    selected = menu.add_command("Selected", lambda context: None)
    disabled = menu.add_command("Disabled", lambda context: None)
    following = menu.add_command("Following", lambda context: None)
    menu.disable_command(disabled)
    menu._selected_index = selected.position

    menu.delete_command(selected)
    assert menu.commands[menu._selected_index] is following

    menu.delete_command(following)
    assert menu.commands[menu._selected_index] is first

    menu.delete_command(first)
    assert menu._selected_index == len(menu.commands)


def test_command_can_delete_itself_during_activation() -> None:
    _, menu = make_menu()
    command = menu.add_command("Delete", lambda context: menu.delete_command(command))

    press(menu, "enter")

    assert menu.commands == ()
    assert menu._selected_index == 0


def test_delete_command_rejects_foreign_and_invalid_handles() -> None:
    _, menu = make_menu()
    _, foreign_menu = make_menu()
    foreign = foreign_menu.add_command("Foreign", lambda context: None)

    with pytest.raises(ValueError):
        menu.delete_command(foreign)
    with pytest.raises(ValueError):
        menu.delete_command(object())  # type: ignore[arg-type]
