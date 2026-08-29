from importlib.resources import files
from inspect import getdoc

import tuiloom
from tuiloom import (
    CommandContext,
    ContentPanel,
    GlobalCommand,
    KeyBinding,
    KeyMap,
    MenuCommand,
    ScreenContext,
    TerminalApp,
    TerminalMenu,
)


def test_public_api_contains_only_intentional_symbols() -> None:
    expected = {
        "AutoScrollMode",
        "CommandBehavior",
        "CommandContext",
        "ContentPanel",
        "ContentSource",
        "GlobalCommand",
        "InputBehavior",
        "KeyBinding",
        "KeyMap",
        "MenuCommand",
        "MessageKey",
        "ScreenContext",
        "TerminalApp",
        "TerminalMenu",
        "hyperlink",
    }
    assert set(tuiloom.__all__) == expected
    assert all(getattr(tuiloom, name) is not None for name in expected)
    assert not hasattr(tuiloom, "Command")
    assert not hasattr(tuiloom, "CommandDict")
    assert not hasattr(tuiloom, "MessageRegistry")


def test_package_declares_inline_typing() -> None:
    assert files("tuiloom").joinpath("py.typed").is_file()


def test_public_classes_and_methods_have_documentation() -> None:
    classes = (
        CommandContext,
        ContentPanel,
        GlobalCommand,
        KeyBinding,
        KeyMap,
        MenuCommand,
        ScreenContext,
        TerminalApp,
        TerminalMenu,
    )
    for documented_class in classes:
        assert getdoc(documented_class), documented_class.__name__

    methods: dict[type[object], tuple[str, ...]] = {
        TerminalApp: (
            "__init__",
            "name",
            "global_content_source",
            "keymap",
            "global_commands",
            "main_menu",
            "set_main_menu",
            "add_global_command",
            "set_global_command_binding",
            "set_global_command_label",
            "set_global_command_behavior",
            "add_message",
            "disable_message",
            "enable_message",
            "run",
        ),
        TerminalMenu: (
            "__init__",
            "app",
            "screen_context",
            "commands",
            "is_main",
            "show",
            "auto_scroll",
            "content_panels",
            "add_content_source",
            "set_content_panel_source",
            "set_content_panel_description",
            "set_content_panel_auto_scroll",
            "move_content_panel",
            "remove_content_panel",
            "add_command",
            "add_menu",
            "set_command_label",
            "set_command_behavior",
            "move_command",
            "disable_command",
            "enable_command",
            "set_exit_label",
            "set_global_command_behavior",
            "clear_global_command_behavior",
            "disable_global_command",
            "enable_global_command",
            "set_content_source",
            "run_with_output",
            "enter_input_mode",
            "leave_input_mode",
            "show_alert",
            "clear_alert",
            "show_message",
            "clear_message",
            "disable_message",
            "enable_message",
            "is_message_enabled",
            "run",
            "stop",
        ),
        KeyMap: ("bindings", "set_binding", "action_for"),
    }
    for public_type, names in methods.items():
        for name in names:
            member: object = getattr(public_type, name)
            if isinstance(member, property):
                member = member.fget
            assert getdoc(member), f"{public_type.__name__}.{name}"


def test_accidental_runtime_state_is_not_public() -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(app, ScreenContext("main", "Main"))
    for name in ("input_handler", "running", "content_renderer"):
        assert not hasattr(app, name)
        assert not hasattr(menu, name)
