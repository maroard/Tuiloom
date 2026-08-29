from __future__ import annotations

import pytest

from tuiloom import (
    CommandContext,
    KeyBinding,
    MessageKey,
    ScreenContext,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.input_handler.input_event import InputEvent


def make_menu(content: str | None = None) -> tuple[TerminalApp, TerminalMenu]:
    app = TerminalApp("App")
    menu = TerminalMenu(app, ScreenContext("main", "Main"), content_source=content)
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
    assert menu._input_buffer == "e\u0301"
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
    assert menu._input_buffer == "x"
    menu._handle_event(event("escape"))
    assert menu._input_behavior is None
    assert menu._input_buffer == ""


def test_alert_without_callback_does_not_close_on_enter() -> None:
    _, menu = make_menu(content="content")
    menu.show_alert("Blocking")
    menu._handle_event(event("enter"))
    assert menu._alert_text == "Blocking"
    assert menu._alert_prompt is None
    menu.clear_alert()
    assert menu._alert_text is None


def test_confirmable_alert_closes_only_after_normal_callback() -> None:
    app, menu = make_menu()
    contexts: list[CommandContext] = []
    menu.show_alert("Confirm", on_confirm=contexts.append)
    assert menu._alert_prompt == "Press Enter to continue"
    menu._handle_event(event("enter"))
    assert len(contexts) == 1
    context = contexts[0]
    assert context.command is None
    assert context.binding == KeyBinding("enter")
    assert menu._alert_text is None

    def fail(context: object) -> None:
        raise RuntimeError("failed")

    menu.show_alert("Still here", on_confirm=fail, prompt="Continue?")
    with pytest.raises(RuntimeError, match="failed"):
        menu._handle_event(event("enter"))
    assert menu._alert_text == "Still here"
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
    assert menu._input_buffer == "abc"
    menu.clear_alert()
    assert menu._display_input_buffer() == "***"


def test_hidden_menu_discards_local_input_but_keeps_global_and_back() -> None:
    app, menu = make_menu()
    calls: list[str] = []
    menu.add_command("Local", lambda context: calls.append("local"))
    app.add_global_command(
        KeyBinding("g"), "Global", lambda context: calls.append("global")
    )
    menu.show = False
    menu._running = True
    menu._handle_event(event("enter"))
    menu._handle_event(event("g", "g"))
    assert calls == ["global"]
    menu.show = True
    assert menu._selected_index == 0
    menu.show = False
    menu._handle_event(event("escape"))
    assert not menu._running


def test_registered_messages_validate_and_combine_suppression() -> None:
    app, menu = make_menu()
    app.add_message("saved", "Saved")
    assert menu.show_message("saved")
    assert menu.screen_context.message == "Saved"
    menu.disable_message("saved")
    menu.screen_context.message = "Keep"
    assert not menu.show_message("saved")
    assert menu.screen_context.message == "Keep"
    assert not menu.is_message_enabled("saved")
    menu.enable_message("saved")
    app.disable_message("saved")
    assert not menu.is_message_enabled("saved")
    app.enable_message("saved")
    assert menu.is_message_enabled("saved")
    menu.clear_message()
    assert menu.screen_context.message is None
    with pytest.raises(KeyError):
        menu.disable_message("missing")
    with pytest.raises(KeyError):
        menu.show_message("missing")
    assert MessageKey.TASK_EXIT_CHOICES.value == "task_exit_choices"
    assert MessageKey.TASK_STOPPING.value == "task_stopping"


@pytest.mark.parametrize("width", [True, False, 0, -1, 1.5])
def test_screen_width_rejects_invalid_construction_and_mutation(width: object) -> None:
    with pytest.raises(ValueError):
        ScreenContext("main", "Main", width=width)  # type: ignore[arg-type]
    context = ScreenContext("main", "Main", width=4)
    with pytest.raises(ValueError):
        context.width = width  # type: ignore[assignment]
    assert context.width == 4


def test_show_and_content_spacing_are_validated() -> None:
    app = TerminalApp("App")
    with pytest.raises(TypeError):
        TerminalMenu(
            app,
            ScreenContext("main", "Main"),
            content_spacing=1,  # type: ignore[arg-type]
        )
    menu = TerminalMenu(app, ScreenContext("main", "Main"))
    with pytest.raises(TypeError):
        menu.show = 1  # type: ignore[assignment]


def test_auto_scroll_validation_and_content_replacement() -> None:
    _, menu = make_menu()
    assert menu.auto_scroll is None
    menu.auto_scroll = "smart"
    assert menu.auto_scroll == "smart"
    with pytest.raises(ValueError):
        menu.auto_scroll = "bottom"  # type: ignore[assignment]
    menu.set_content_source("new")
    assert menu._content_source == "new"


def test_active_content_replacement_forwards_its_description() -> None:
    _, menu = make_menu(content="old")
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
    source = iter(["new"])

    menu.set_content_source(source, description="Generating")

    assert menu._content_source is source
    assert installed == [(source, "Generating")]


def test_menu_run_builds_resources_shows_no_content_and_closes_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, menu = make_menu()

    class Loop:
        def __init__(self) -> None:
            self.closed = False

        def run(self) -> None:
            menu._stop_immediately()

        def close(self) -> None:
            self.closed = True

    loop = Loop()
    app._input_handler = object()  # type: ignore[assignment]
    monkeypatch.setattr(menu, "_create_event_loop", lambda: loop)
    menu.run()
    assert loop.closed
    assert "No content source" in (menu.screen_context.message or "")
    assert menu._event_loop is None


def test_menu_run_requires_application_lifecycle() -> None:
    _, menu = make_menu()
    with pytest.raises(RuntimeError, match="outside"):
        menu.run()


def test_alert_back_and_unbound_events_are_safely_consumed() -> None:
    _, menu = make_menu()
    menu._running = True
    menu.show_alert("Alert")
    menu._handle_event(InputEvent(None, "paste"))
    assert menu._running
    menu._handle_event(event("escape"))
    assert not menu._running


def test_exit_selection_and_content_scroll_without_renderer() -> None:
    _, menu = make_menu(content="content")
    menu._running = True
    menu._selected_index = len(menu.commands)
    menu._handle_event(event("enter"))
    assert not menu._running
    menu._focus = "content"
    menu._handle_event(event("left"))
