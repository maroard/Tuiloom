import pytest

from tuiloom import CommandContext, ScreenContext, TerminalApp, TerminalMenu


def do_nothing(context: CommandContext) -> None:
    pass


def test_global_command_dispatch_is_internal() -> None:
    calls: list[str] = []
    app = TerminalApp("Example")
    menu = TerminalMenu(app, ScreenContext("Example", "Menu", "Menu"))
    app.add_global_command(
        "x",
        "Run X",
        lambda context: calls.append(context.command_key),
    )
    assert not hasattr(app, "handle_global_command")
    assert app._handle_global_command("X", menu) is True
    assert calls == ["X"]
    assert app._handle_global_command("missing", menu) is False


def test_global_command_key_cannot_contain_multiple_characters() -> None:
    app = TerminalApp("Example")

    with pytest.raises(ValueError, match="single alphabetic character"):
        app.add_global_command("xy", "Run X then Y", do_nothing)


def test_global_command_key_cannot_be_empty() -> None:
    app = TerminalApp("Example")

    with pytest.raises(ValueError, match="single alphabetic character"):
        app.add_global_command("", "Empty", do_nothing)


def test_menu_inherits_application_global_content_source() -> None:
    app = TerminalApp("Example", global_content_source="global")
    menu = TerminalMenu(
        app,
        ScreenContext(
            app_name="Example",
            menu_name="Submenu",
            title="Submenu",
        ),
    )

    assert menu._content_source == "global"


def test_menu_local_content_source_overrides_application_global_source() -> None:
    app = TerminalApp("Example", global_content_source="global")
    menu = TerminalMenu(
        app,
        ScreenContext(
            app_name="Example",
            menu_name="Submenu",
            title="Submenu",
        ),
        content_source="local",
    )

    assert menu._content_source == "local"


def test_application_adds_and_resolves_custom_message() -> None:
    app = TerminalApp("Example")

    app.add_message("saved", "Saved")

    assert app._get_message("saved") == "Saved"


def test_application_disables_and_reenables_message_globally() -> None:
    app = TerminalApp("Example")
    app.add_message("saved", "Saved")

    app.disable_message("saved")
    assert app._get_message("saved") is None

    app.enable_message("saved")
    assert app._get_message("saved") == "Saved"


def test_message_registry_is_private_to_application() -> None:
    app = TerminalApp("Example")

    assert not hasattr(app, "message_registry")
    assert hasattr(app, "_message_registry")


def test_application_does_not_store_built_in_message_keys() -> None:
    assert not hasattr(TerminalApp, "_NO_CONTENT_SOURCE_MESSAGE")
    assert not hasattr(TerminalApp, "_UNKNOWN_COMMAND_MESSAGE")


def test_application_message_disable_applies_to_every_menu() -> None:
    app = TerminalApp("Example")
    first_menu = TerminalMenu(
        app,
        ScreenContext("Example", "First", "First"),
    )
    second_menu = TerminalMenu(
        app,
        ScreenContext("Example", "Second", "Second"),
    )

    app.disable_message("unknown_command")
    first_menu._handle_unknown_command("wat")
    second_menu._handle_unknown_command("wat")

    assert first_menu.screen_context.message is None
    assert second_menu.screen_context.message is None


def test_menu_message_disable_only_applies_to_that_menu() -> None:
    app = TerminalApp("Example")
    first_menu = TerminalMenu(
        app,
        ScreenContext("Example", "First", "First"),
    )
    second_menu = TerminalMenu(
        app,
        ScreenContext("Example", "Second", "Second"),
    )

    first_menu.disable_message("unknown_command")
    first_menu._handle_unknown_command("wat")
    second_menu._handle_unknown_command("wat")

    assert first_menu.screen_context.message is None
    assert second_menu.screen_context.message == "Unknown command 'wat'"


def test_menu_can_reenable_a_locally_disabled_message() -> None:
    app = TerminalApp("Example")
    menu = TerminalMenu(
        app,
        ScreenContext("Example", "Menu", "Menu"),
    )
    menu.disable_message("unknown_command")
    menu._handle_unknown_command("wat")
    assert menu.screen_context.message is None

    menu.enable_message("unknown_command")
    menu._handle_unknown_command("wat")

    assert menu.screen_context.message == "Unknown command 'wat'"


def test_menu_enable_cannot_override_application_disable() -> None:
    app = TerminalApp("Example")
    menu = TerminalMenu(
        app,
        ScreenContext("Example", "Menu", "Menu"),
    )
    app.disable_message("unknown_command")

    menu.enable_message("unknown_command")
    menu._handle_unknown_command("wat")

    assert menu.screen_context.message is None
