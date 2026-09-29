import pytest

from tuiloom import MenuDisplay, MessageKey, TerminalApp, TerminalMenu
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.key_binding import KeyBinding


def make_menu() -> tuple[TerminalApp, TerminalMenu]:
    app = TerminalApp("App")
    app.add_message("credit", "Credits")
    app.add_message("other", "Credits")
    return app, TerminalMenu(app, MenuDisplay("main", "Main"))


def test_toggle_tracks_identity_instead_of_text() -> None:
    _, menu = make_menu()
    assert menu.active_message_key is None
    for _ in range(3):
        assert menu.toggle_message("credit")
        assert menu.active_message_key == "credit"
        assert menu.display_state.message == "Credits"
        assert not menu.toggle_message("credit")
        assert menu.active_message_key is None
        assert menu.display_state.message is None
    assert menu.show_message("other")
    assert menu.toggle_message("credit")
    assert menu.active_message_key == "credit"
    menu.clear_message()
    assert menu.active_message_key is None
    assert menu.display_state.message is None


@pytest.mark.parametrize("text", ["Map note", "Credits", None])
def test_direct_assignment_clears_message_identity(text: str | None) -> None:
    _, menu = make_menu()
    menu.show_message("credit")
    menu.display_state.message = text
    assert menu.active_message_key is None
    assert menu.toggle_message("credit")
    assert menu.display_state.message == "Credits"


@pytest.mark.parametrize("global_suppression", [False, True])
def test_suppression_preserves_current_message_and_allows_hiding(
    global_suppression: bool,
) -> None:
    app, menu = make_menu()
    owner = app if global_suppression else menu
    menu.show_message("other")
    owner.disable_message("credit")
    assert not menu.toggle_message("credit")
    assert not menu.show_message("credit")
    assert menu.active_message_key == "other"
    assert menu.display_state.message == "Credits"
    owner.enable_message("credit")
    assert menu.toggle_message("credit")
    owner.disable_message("credit")
    assert menu.active_message_key == "credit"
    assert not menu.toggle_message("credit")
    assert menu.active_message_key is None
    assert menu.display_state.message is None


def test_unknown_key_preserves_current_message() -> None:
    _, menu = make_menu()
    menu.show_message("credit")
    for method in (menu.toggle_message, menu.show_message):
        with pytest.raises(KeyError):
            method("missing")
        assert menu.active_message_key == "credit"
        assert menu.display_state.message == "Credits"


def test_automatic_messages_update_identity_and_respect_suppression() -> None:
    app, menu = make_menu()
    app.enable_message(MessageKey.UNKNOWN_COMMAND)
    menu.show_message("credit")
    assert menu._show_automatic_message(MessageKey.UNKNOWN_COMMAND, command="oops")
    assert menu.active_message_key == MessageKey.UNKNOWN_COMMAND
    assert menu.display_state.message == "Unknown command 'oops'"
    menu.show_message("credit")
    menu.disable_message(MessageKey.UNKNOWN_COMMAND)
    assert not menu._show_automatic_message(MessageKey.UNKNOWN_COMMAND, command="oops")
    assert menu.active_message_key == "credit"
    assert menu.display_state.message == "Credits"
    assert menu.show_message(MessageKey.NO_CONTENT_SOURCE)
    assert menu.active_message_key == MessageKey.NO_CONTENT_SOURCE


def test_unknown_command_is_opt_in_and_preserves_existing_message() -> None:
    app, menu = make_menu()
    menu.show_message("credit")
    assert not menu.is_message_enabled(MessageKey.UNKNOWN_COMMAND)
    menu._handle_event(InputEvent(KeyBinding("x"), "x"))
    assert menu.display_state.message == "Credits"
    assert menu.active_message_key == "credit"
    app.enable_message(MessageKey.UNKNOWN_COMMAND)
    menu._handle_event(InputEvent(KeyBinding("x"), "x"))
    assert menu.display_state.message == "Unknown command 'x'"
    assert menu.active_message_key == MessageKey.UNKNOWN_COMMAND


def test_active_message_key_is_read_only() -> None:
    _, menu = make_menu()
    with pytest.raises(AttributeError):
        menu.active_message_key = "credit"  # type: ignore[misc]


def test_message_identity_does_not_change_context_value_semantics() -> None:
    _, menu = make_menu()
    menu.show_message("credit")
    plain = MenuDisplay("main", "Main", message="Credits")
    assert menu.display_state == plain
    assert repr(menu.display_state) == repr(plain)
    other_menu = TerminalMenu(menu.app, plain)
    assert other_menu.active_message_key is None
