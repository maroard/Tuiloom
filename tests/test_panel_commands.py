import pytest

from tuiloom import (
    KeyBinding,
    MenuDisplay,
    PanelCommandContext,
    PanelKeyCommand,
    ScreenContent,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.task_exit import TaskExitState


def make_menu() -> tuple[TerminalApp, TerminalMenu]:
    app = TerminalApp("App")
    menu = TerminalMenu(app, MenuDisplay("main", "Main"))
    return app, menu


def press(menu: TerminalMenu, key: str) -> None:
    menu._handle_event(InputEvent(KeyBinding(key), key if len(key) == 1 else None))


def test_panel_shortcut_follows_focus_and_passes_its_context() -> None:
    app, menu = make_menu()
    first = menu.add_content_panel(ScreenContent.static("first"))
    second = menu.add_content_panel(ScreenContent.static("second"))
    calls: list[PanelCommandContext] = []
    first_command = first.add_key_command(KeyBinding("x"), "First", calls.append)
    second_command = second.add_key_command(KeyBinding("x"), "Second", calls.append)

    assert first.key_commands == (first_command,)
    assert isinstance(first_command, PanelKeyCommand)
    assert second.key_commands == (second_command,)
    assert menu.focused_panel is None
    press(menu, "x")
    assert calls == []
    press(menu, "tab")
    assert menu.focused_panel is first
    press(menu, "x")
    press(menu, "tab")
    assert menu.focused_panel is second
    press(menu, "x")
    assert [
        (call.app, call.menu, call.panel, call.command, call.binding) for call in calls
    ] == [
        (app, menu, first, first_command, KeyBinding("x")),
        (app, menu, second, second_command, KeyBinding("x")),
    ]

    second.remove_key_command(second_command)
    assert second.key_commands == ()
    press(menu, "x")
    assert len(calls) == 2


def test_panel_priority_only_overrides_global_for_focused_panel() -> None:
    app, menu = make_menu()
    first = menu.add_content_panel(ScreenContent.static("first"))
    second = menu.add_content_panel(ScreenContent.static("second"))
    calls: list[str] = []
    app.add_global_command(
        KeyBinding("x"), "Global", lambda context: calls.append("global")
    )
    first.add_key_command(
        KeyBinding("x"), "First", lambda context: calls.append("first")
    )
    second.add_key_command(
        KeyBinding("x", priority=True), "Second", lambda context: calls.append("second")
    )

    press(menu, "x")
    press(menu, "tab")
    press(menu, "x")
    press(menu, "tab")
    press(menu, "x")
    assert calls == ["global", "global", "second"]
    assert KeyBinding("x", priority=True) == KeyBinding("x")


def test_panel_shortcuts_are_blocked_in_input_and_alert_modes() -> None:
    _, menu = make_menu()
    panel = menu.add_content_panel(ScreenContent.static("content"))
    calls: list[str] = []
    panel.add_key_command(
        KeyBinding("x"), "Panel", lambda context: calls.append("panel")
    )
    press(menu, "tab")
    menu.enter_input_mode("Text: ", lambda text: None)
    assert menu.focused_panel is None
    press(menu, "x")
    menu.leave_input_mode()
    menu.show_alert("Wait")
    assert menu.focused_panel is None
    press(menu, "x")
    menu.clear_alert()
    assert menu.focused_panel is panel
    assert calls == []


def test_panel_shortcuts_are_blocked_in_task_exit_view() -> None:
    _, menu = make_menu()
    panel = menu.add_content_panel(ScreenContent.static("content"))
    calls: list[str] = []
    panel.add_key_command(
        KeyBinding("x", priority=True), "Panel", lambda context: calls.append("panel")
    )
    press(menu, "tab")
    menu._task_exit = TaskExitState("choice", 0, panel, 0, 0.0, (panel,))
    assert menu.focused_panel is None
    press(menu, "x")
    assert calls == []


@pytest.mark.parametrize("key", ["tab", "escape", "up", "down", "left", "right"])
def test_system_keys_cannot_be_panel_shortcuts_even_with_priority(key: str) -> None:
    _, menu = make_menu()
    panel = menu.add_content_panel(ScreenContent.static("content"))
    with pytest.raises(ValueError, match="reserved"):
        panel.add_key_command(
            KeyBinding(key, priority=True), "Reserved", lambda context: None
        )


def test_panel_command_registration_and_removal_validate_ownership() -> None:
    _, menu = make_menu()
    first = menu.add_content_panel(ScreenContent.static("first"))
    second = menu.add_content_panel(ScreenContent.static("second"))
    command = first.add_key_command(KeyBinding("x"), "X", lambda context: None)
    with pytest.raises(ValueError):
        first.add_key_command(
            KeyBinding("x", priority=True), "Again", lambda context: None
        )
    with pytest.raises(ValueError):
        second.remove_key_command(command)
    first.remove_key_command(command)
    with pytest.raises(ValueError):
        first.remove_key_command(command)
    first.remove()
    with pytest.raises(ValueError):
        first.add_key_command(KeyBinding("y"), "Y", lambda context: None)


@pytest.mark.parametrize("key", ["left", "right"])
def test_shift_horizontal_arrow_can_invoke_a_focused_panel_command(key: str) -> None:
    _, menu = make_menu()
    panel = menu.add_content_panel(ScreenContent.static("content"))
    calls: list[KeyBinding] = []
    panel.add_key_command(
        KeyBinding(key, shift=True),
        "Browse turns",
        lambda context: calls.append(context.binding),
    )
    press(menu, "tab")
    menu._handle_event(InputEvent(KeyBinding(key, shift=True)))
    assert calls == [KeyBinding(key, shift=True)]


@pytest.mark.parametrize("key", ["tab", "escape", "up", "down"])
def test_other_shifted_system_keys_remain_reserved(key: str) -> None:
    _, menu = make_menu()
    panel = menu.add_content_panel(ScreenContent.static("content"))
    with pytest.raises(ValueError, match="reserved"):
        panel.add_key_command(
            KeyBinding(key, shift=True), "Reserved", lambda context: None
        )
