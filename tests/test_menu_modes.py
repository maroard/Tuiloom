from __future__ import annotations

import pytest

from tuiloom import (
    CommandContext,
    KeyBinding,
    MenuDisplay,
    ScreenContent,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.input_handler.input_event import InputEvent


def make_menu(
    content: ScreenContent | str | None = None,
) -> tuple[TerminalApp, TerminalMenu]:
    app = TerminalApp("App")
    configured = ScreenContent.static(content) if isinstance(content, str) else content
    menu = TerminalMenu(app, MenuDisplay("main", "Main"))
    if configured is not None:
        menu.add_content_panel(configured)
    return app, menu


def event(key: str, text: str | None = None) -> InputEvent:
    return InputEvent(KeyBinding(key), text)


def test_hidden_input_masks_and_deletes_whole_unicode_graphemes() -> None:
    _, menu = make_menu()
    submitted: list[str] = []
    menu.enter_input_mode("Password: ", submitted.append, hidden=True)
    menu._handle_event(InputEvent(None, "e\u0301👨‍👩‍👧"))
    assert menu._display_input_buffer() == "**"
    menu._handle_event(event("backspace"))
    assert menu._input is not None
    assert menu._input.buffer == "e\u0301"
    assert menu._display_input_buffer() == "*"
    menu._handle_event(event("enter"))
    assert submitted == ["e\u0301"]


def test_input_mode_disables_globals_and_escape_leaves_it() -> None:
    app, menu = make_menu()
    calls: list[str] = []
    app.add_global_command(KeyBinding("x"), "X", lambda context: calls.append("x"))
    menu.enter_input_mode("Value: ", calls.append)
    menu._handle_event(event("x", "x"))
    assert calls == []
    assert menu._input is not None
    assert menu._input.buffer == "x"
    menu._handle_event(event("escape"))
    assert menu._input is None
    assert menu._display_input_buffer() == ""


def test_alert_without_callback_does_not_close_on_enter() -> None:
    _, menu = make_menu(content=ScreenContent.static("content"))
    menu.show_alert("Blocking")
    menu._handle_event(event("enter"))
    assert menu._alert is not None
    assert menu._alert.text == "Blocking"
    assert menu._alert is not None
    assert menu._alert.prompt is None
    menu.clear_alert()
    assert menu._alert is None


def test_confirmable_alert_closes_only_after_normal_callback() -> None:
    app, menu = make_menu()
    contexts: list[CommandContext] = []
    menu.show_alert("Confirm", on_confirm=contexts.append)
    assert menu._alert is not None
    assert menu._alert.prompt == "Press Enter to continue"
    menu._handle_event(event("enter"))
    assert len(contexts) == 1
    context = contexts[0]
    assert context.command is None
    assert context.binding == KeyBinding("enter")
    assert menu._alert is None

    def fail(context: object) -> None:
        raise RuntimeError("failed")

    menu.show_alert("Still here", on_confirm=fail, prompt="Continue?")
    with pytest.raises(RuntimeError, match="failed"):
        menu._handle_event(event("enter"))
    assert menu._alert is not None
    assert menu._alert.text == "Still here"
    assert app.name == "App"


def test_alert_suspends_and_restores_free_input_and_allows_globals() -> None:
    app, menu = make_menu()
    global_calls: list[str] = []
    app.add_global_command(
        KeyBinding("g"), "Global", lambda context: global_calls.append("g")
    )
    menu.enter_input_mode("Secret: ", lambda value: None, hidden=True)
    menu._handle_event(InputEvent(None, "abc"))
    menu.show_alert("Notice")
    menu._handle_event(event("g", "g"))
    assert global_calls == ["g"]
    assert menu._input is not None
    assert menu._input.buffer == "abc"
    menu.clear_alert()
    assert menu._display_input_buffer() == "***"


def test_hidden_menu_discards_local_input_but_keeps_global_and_back() -> None:
    app, menu = make_menu()
    calls: list[str] = []
    menu.add_command("Local", lambda context: calls.append("local"))
    app.add_global_command(
        KeyBinding("g"), "Global", lambda context: calls.append("global")
    )
    menu.hide_menu()
    menu._running = True
    menu._handle_event(event("enter"))
    menu._handle_event(event("g", "g"))
    assert calls == ["global"]
    menu.show_menu()
    assert menu._selected_index == 0
    menu.hide_menu()
    menu._handle_event(event("escape"))
    assert not menu._running


def test_registered_messages_validate_and_combine_suppression() -> None:
    app, menu = make_menu()
    app.add_message("saved", "Saved")
    assert menu.show_message("saved")
    assert menu.display_state.message == "Saved"
    menu.disable_message("saved")
    menu.display_state.message = "Keep"
    assert not menu.show_message("saved")
    assert menu.display_state.message == "Keep"
    assert not menu.is_message_enabled("saved")
    menu.enable_message("saved")
    app.disable_message("saved")
    assert not menu.is_message_enabled("saved")
    app.enable_message("saved")
    assert menu.is_message_enabled("saved")
    menu.clear_message()
    assert menu.display_state.message is None
    with pytest.raises(KeyError):
        menu.disable_message("missing")
    with pytest.raises(KeyError):
        menu.show_message("missing")


@pytest.mark.parametrize("width", [True, False, 0, -1, 1.5])
def test_screen_width_rejects_invalid_construction_and_mutation(width: object) -> None:
    with pytest.raises(ValueError):
        MenuDisplay("main", "Main", width=width)  # type: ignore[arg-type]
    context = MenuDisplay("main", "Main", width=4)
    with pytest.raises(ValueError):
        context.width = width  # type: ignore[assignment]
    assert context.width == 4


@pytest.mark.parametrize("strict_width", [None, 0, 1, "true"])
def test_strict_width_rejects_non_booleans(strict_width: object) -> None:
    with pytest.raises(TypeError, match="strict_width"):
        MenuDisplay("main", "Main", strict_width=strict_width)  # type: ignore[arg-type]
    context = MenuDisplay("main", "Main", strict_width=True)
    with pytest.raises(TypeError, match="strict_width"):
        context.strict_width = strict_width  # type: ignore[assignment]
    assert context.strict_width is True


def test_strict_width_preserves_existing_positional_arguments() -> None:
    context = MenuDisplay("main", "Main", 12, "Text", "Message")
    assert context.strict_width is False
    assert context.text == "Text"
    assert context.message == "Message"


def test_content_spacing_is_validated_and_frame_show_is_removed() -> None:
    app = TerminalApp("App")
    with pytest.raises(TypeError):
        TerminalMenu(
            app,
            MenuDisplay("main", "Main"),
            content_spacing=1,  # type: ignore[arg-type]
        )
    menu = TerminalMenu(app, MenuDisplay("main", "Main"))
    assert not hasattr(menu, "show")
    with pytest.raises(TypeError):
        TerminalMenu(app, menu.display_state, show=False)  # type: ignore[call-arg]


def test_auto_scroll_validation_and_content_replacement() -> None:
    _, menu = make_menu(content="old")
    panel = menu.content_panels[0]
    assert panel.auto_scroll is None
    panel.set_auto_scroll("smart")
    assert panel.auto_scroll == "smart"
    with pytest.raises(ValueError):
        panel.set_auto_scroll("bottom")  # type: ignore[arg-type]
    panel.set_content(ScreenContent.static("new"))
    assert panel.content == ScreenContent.static("new")


def test_active_content_replacement_forwards_its_description() -> None:
    _, menu = make_menu(content=ScreenContent.static("old"))
    installed: list[tuple[object, str]] = []

    class Loop:
        def replace_content_panel(
            self,
            panel: object,
            source: object,
        ) -> None:
            installed.append((source, menu.content_panels[0].description))

    menu._running = True
    menu._event_loop = Loop()  # type: ignore[assignment]
    source = ScreenContent.stream(iter(["new"]))

    panel = menu.content_panels[0]
    panel.set_description("Generating")
    panel.set_content(source)

    assert menu.content_panels == (panel,)
    assert installed == [(source, "Generating")]


def test_alert_back_and_unbound_events_are_safely_consumed() -> None:
    _, menu = make_menu()
    menu._running = True
    menu.show_alert("Alert")
    menu._handle_event(InputEvent(None, "paste"))
    assert menu._running
    menu._handle_event(event("escape"))
    assert not menu._running


def test_exit_selection_and_content_scroll_without_renderer() -> None:
    _, menu = make_menu(content=ScreenContent.static("content"))
    menu._running = True
    menu._selected_index = len(menu.commands)
    menu._handle_event(event("enter"))
    assert not menu._running
    menu._focused_panel = menu.content_panels[0]
    menu._handle_event(event("left"))


def test_focus_cycles_through_each_content_panel_and_back_to_menu() -> None:
    _, menu = make_menu(
        content=ScreenContent.static("\n".join(str(index) for index in range(30)))
    )
    first = menu.content_panels[0]
    second = menu.add_content_panel(
        ScreenContent.static("\n".join(f"b{index}" for index in range(30))),
        description="Second",
    )

    menu._handle_event(event("tab"))
    assert menu._focused_panel is first
    menu._handle_event(event("tab"))
    assert menu._focused_panel is second
    menu._handle_event(event("tab"))
    assert menu._focused_panel is None


def test_removing_focused_panel_advances_to_next_panel() -> None:
    _, menu = make_menu(content=ScreenContent.static("first"))
    focused = menu.add_content_panel(
        ScreenContent.static("second"), description="Second"
    )
    following = menu.add_content_panel(
        ScreenContent.static("third"), description="Third"
    )
    menu._focused_panel = focused

    focused.remove()

    assert menu._focused_panel is following
