from importlib.resources import files
from inspect import getdoc, signature

import tuiloom
from tuiloom import (
    ChoiceContext,
    ChoiceOption,
    CommandContext,
    ContentPanel,
    ContentSize,
    GlobalCommand,
    KeyBinding,
    KeyMap,
    MenuChoice,
    MenuCommand,
    MenuDisplay,
    ScreenContent,
    StatusBar,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.event_loop.event_loop import EventLoop
from tuiloom.render.terminal_renderer import TerminalRenderer


def test_public_api_contains_only_intentional_symbols() -> None:
    expected = {
        "AnimatedText",
        "AnimationFrame",
        "AutoScrollMode",
        "ChoiceCallback",
        "ChoiceContext",
        "ChoiceOption",
        "CommandCallback",
        "CommandContext",
        "ContentPanel",
        "ContentRefreshMode",
        "ContentSize",
        "GlobalCommand",
        "InputCallback",
        "KeyBinding",
        "KeyAction",
        "KeyMap",
        "MenuCommand",
        "MenuChoice",
        "MenuPresentation",
        "MessageKey",
        "MenuDisplay",
        "ScreenContent",
        "StatusBar",
        "TerminalApp",
        "TerminalMenu",
        "TextColor",
        "display_width",
        "hyperlink",
        "rainbow_color",
        "style",
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
        ChoiceContext,
        ChoiceOption,
        CommandContext,
        ContentPanel,
        ContentSize,
        GlobalCommand,
        KeyBinding,
        KeyMap,
        MenuCommand,
        MenuChoice,
        MenuDisplay,
        ScreenContent,
        StatusBar,
        TerminalApp,
        TerminalMenu,
    )
    for documented_class in classes:
        assert getdoc(documented_class), documented_class.__name__

    methods: dict[type[object], tuple[str, ...]] = {
        TerminalApp: (
            "__init__",
            "name",
            "global_content",
            "global_content_factory",
            "keymap",
            "global_commands",
            "main_menu",
            "set_main_menu",
            "add_global_command",
            "set_global_command_binding",
            "set_global_command_label",
            "set_global_command_callback",
            "add_message",
            "disable_message",
            "enable_message",
            "run",
        ),
        TerminalMenu: (
            "__init__",
            "app",
            "display_state",
            "commands",
            "is_main",
            "presentation",
            "menu_visible",
            "show_menu",
            "hide_menu",
            "toggle_menu",
            "content_panels",
            "status_bar",
            "set_status_bar",
            "clear_status_bar",
            "refresh_status_bar",
            "add_content_panel",
            "add_command",
            "add_choice",
            "set_choice_index",
            "set_choice_callback",
            "add_submenu",
            "remove_command",
            "set_command_label",
            "set_command_callback",
            "move_command",
            "disable_command",
            "enable_command",
            "set_exit_label",
            "set_global_command_callback",
            "clear_global_command_callback",
            "disable_global_command",
            "enable_global_command",
            "start_output_task",
            "enter_input_mode",
            "leave_input_mode",
            "show_alert",
            "clear_alert",
            "show_message",
            "active_message_key",
            "toggle_message",
            "clear_message",
            "disable_message",
            "enable_message",
            "is_message_enabled",
            "stop",
        ),
        ContentPanel: (
            "content",
            "description",
            "position",
            "auto_scroll",
            "weight",
            "min_height",
            "max_height",
            "collapsed",
            "collapsed_height",
            "collapse",
            "expand",
            "toggle_collapse",
            "set_collapsed_height",
            "set_layout",
            "update_layout",
            "set_content",
            "refresh",
            "set_description",
            "set_auto_scroll",
            "move",
            "remove",
        ),
        MenuCommand: ("label", "callback", "position", "enabled"),
        MenuChoice: (
            "options",
            "rows",
            "selected_index",
            "selected_option",
            "selected_label",
            "on_select",
            "callback",
        ),
        GlobalCommand: ("binding", "label", "callback"),
        ScreenContent: ("static", "lines", "stream", "dynamic", "responsive"),
        StatusBar: ("static", "dynamic", "responsive"),
        KeyMap: (
            "bindings",
            "set_binding",
            "action_for",
            "copy",
            "focus",
            "up",
            "down",
            "left",
            "right",
            "activate",
            "back",
        ),
    }
    for public_type, names in methods.items():
        for name in names:
            member: object = getattr(public_type, name)
            if isinstance(member, property):
                member = member.fget
            assert getdoc(member), f"{public_type.__name__}.{name}"


def test_discarded_content_panel_aliases_are_absent() -> None:
    for name in ("ScreenContext", "CommandBehavior", "ChoiceBehavior", "InputBehavior"):
        assert not hasattr(tuiloom, name)
    for name in (
        "screen_context",
        "add_menu",
        "delete_command",
        "set_choice_value",
        "set_command_behavior",
        "set_global_command_behavior",
        "clear_global_command_behavior",
        "run_with_output",
        "run",
    ):
        assert not hasattr(TerminalMenu, name)
    assert not hasattr(MenuChoice, "value")
    assert not hasattr(MenuCommand, "behavior")
    assert not hasattr(GlobalCommand, "behavior")
    assert not hasattr(tuiloom, "ContentSource")
    assert not hasattr(TerminalApp, "global_content_source")
    assert not hasattr(TerminalMenu, "set_content_source")
    assert not hasattr(ContentPanel, "set_source")
    assert hasattr(TerminalMenu, "add_content_panel")
    for removed_name in (
        "set_content",
        "auto_scroll",
        "add_content",
        "set_content_panel_source",
        "set_content_panel_description",
        "set_content_panel_auto_scroll",
        "move_content_panel",
        "remove_content_panel",
    ):
        assert not hasattr(TerminalMenu, removed_name)

    for method_name in (
        "set_content",
        "set_description",
        "set_auto_scroll",
        "move",
        "remove",
    ):
        assert callable(getattr(ContentPanel, method_name))


def test_accidental_runtime_state_is_not_public() -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(app, MenuDisplay("main", "Main"))
    for name in ("input_handler", "running", "content_renderer"):
        assert not hasattr(app, name)
        assert not hasattr(menu, name)


def test_removed_single_content_constructor_parameters_are_absent() -> None:
    menu_parameters = signature(TerminalMenu).parameters
    assert "content" not in menu_parameters
    assert "auto_scroll" not in menu_parameters
    assert "content_renderer" not in signature(TerminalRenderer).parameters
    assert "content_renderer" not in signature(EventLoop).parameters


def test_removed_renderer_and_event_loop_aliases_are_absent() -> None:
    for name in (
        "viewport",
        "set_content_renderer",
        "reset_stream_auto_scroll",
        "scroll_up",
        "scroll_down",
        "scroll_left",
        "scroll_right",
    ):
        assert not hasattr(TerminalRenderer, name)
    for name in (
        "install_content",
        "_apply_content",
        "_sync_primary_aliases",
        "_progress_source_replacement",
    ):
        assert not hasattr(EventLoop, name)
