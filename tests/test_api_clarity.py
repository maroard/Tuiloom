from __future__ import annotations

from collections.abc import Iterator

import pytest

import tuiloom
from tuiloom import (
    ChoiceContext,
    ChoiceOption,
    CommandContext,
    KeyBinding,
    KeyMap,
    MenuDisplay,
    ScreenContent,
    TerminalApp,
    TerminalMenu,
    style,
)


def make_menu() -> TerminalMenu:
    return TerminalMenu(TerminalApp("App"), MenuDisplay("main", "Main"))


def test_display_state_exposes_the_mutable_display_configuration() -> None:
    display = tuiloom.MenuDisplay("main", "Main")
    menu = TerminalMenu(TerminalApp("App"), display_state=display)
    assert menu.display_state is display
    assert isinstance(display, MenuDisplay)


def test_command_callback_creation_and_mutation_are_explicit() -> None:
    menu = make_menu()
    calls: list[str] = []
    command = menu.add_command("Action", callback=lambda context: calls.append("old"))
    menu.set_command_callback(command, lambda context: calls.append("new"))
    command.callback(CommandContext(menu.app, menu, command, None))
    assert calls == ["new"]


def test_choice_command_callback_adapts_to_the_selected_option() -> None:
    menu = make_menu()
    calls: list[ChoiceContext] = []
    callback = calls.append
    choice = menu.add_choice(
        "Mode", [ChoiceOption("One"), ChoiceOption("Two")], callback
    )
    menu.set_choice_index(choice, 1)
    assert calls == []
    assert choice.selected_option is choice.options[1]
    assert choice.selected_label == "Two"
    choice.callback(CommandContext(menu.app, menu, choice, KeyBinding("enter")))
    assert calls[0].option is choice.selected_option
    assert calls[0].index == 1
    assert calls[0].binding == KeyBinding("enter")
    assert choice.on_select is callback


def test_choice_selection_callback_has_a_distinct_mutation_method() -> None:
    menu = make_menu()
    calls: list[str] = []
    choice = menu.add_choice("Mode", [ChoiceOption("One")], lambda context: None)
    menu.set_choice_callback(choice, lambda context: calls.append(context.option.label))
    choice.callback(CommandContext(menu.app, menu, choice, None))
    assert calls == ["One"]


def test_submenu_registration_and_command_removal_have_explicit_names() -> None:
    menu = make_menu()
    child = TerminalMenu(menu.app, MenuDisplay("child", "Child"))
    command = menu.add_submenu(child, "Settings")
    assert menu.app._menu_stack == []
    command.callback(CommandContext(menu.app, menu, command, None))
    assert menu.app._menu_stack == [child]
    menu.remove_command(command)
    assert menu.commands == ()
    with pytest.raises(ValueError):
        menu.remove_command(command)


def test_global_command_callbacks_keep_local_overrides_independent() -> None:
    menu = make_menu()
    calls: list[str] = []
    command = menu.app.add_global_command(
        KeyBinding("x"), "Action", callback=lambda context: calls.append("initial")
    )
    menu.app.set_global_command_callback(command, lambda context: calls.append("app"))
    menu.set_global_command_callback(command, lambda context: calls.append("menu"))
    assert menu.app._handle_global_command(KeyBinding("x"), menu)
    menu.clear_global_command_callback(command)
    assert menu.app._handle_global_command(KeyBinding("x"), menu)
    assert calls == ["menu", "app"]


def test_keymap_rejects_a_second_application_owner() -> None:
    keymap = KeyMap()
    app = TerminalApp("First", keymap=keymap)
    app.add_global_command(KeyBinding("x"), "Action", lambda context: None)
    with pytest.raises(ValueError, match="KeyMap.*application"):
        TerminalApp("Second", keymap=keymap)
    with pytest.raises(ValueError):
        keymap.set_binding("up", KeyBinding("x"))


def test_keymap_copy_preserves_bindings_without_sharing_owner_or_mutations() -> None:
    keymap = KeyMap()
    keymap.set_binding("up", KeyBinding("u"))
    first = TerminalApp("First", keymap=keymap)
    first.add_global_command(KeyBinding("x"), "Action", lambda context: None)
    copied = keymap.copy()
    second = TerminalApp("Second", keymap=copied)
    copied.set_binding("up", KeyBinding("x"))
    assert second.keymap.up == KeyBinding("x")
    assert first.keymap.up == KeyBinding("u")


def test_update_layout_keeps_omitted_values_and_can_clear_maximum() -> None:
    menu = make_menu()
    panel = menu.add_content_panel(
        ScreenContent.static("Content"), weight=3, min_height=4, max_height=9
    )
    panel.update_layout(weight=2)
    assert (panel.weight, panel.min_height, panel.max_height) == (2, 4, 9)
    panel.update_layout(max_height=None)
    assert (panel.weight, panel.min_height, panel.max_height) == (2, 4, None)


def test_invalid_partial_layout_update_is_atomic() -> None:
    menu = make_menu()
    panel = menu.add_content_panel(ScreenContent.static("Content"), min_height=4)
    with pytest.raises(ValueError):
        panel.update_layout(weight=2, max_height=3)
    assert (panel.weight, panel.min_height, panel.max_height) == (1, 4, None)


def test_foreground_background_apply_separate_sgr_categories() -> None:
    assert style("Text", foreground="red", background="blue") == (
        "\x1b[31;44mText\x1b[39;49m"
    )


def test_global_content_factory_creates_independent_streams_for_each_menu() -> None:
    created: list[ScreenContent] = []

    def content_factory() -> ScreenContent:
        content = ScreenContent.stream(iter(["One", "Two"]))
        created.append(content)
        return content

    app = TerminalApp("App", global_content_factory=content_factory)
    first = TerminalMenu(app, MenuDisplay("first", "First"))
    second = TerminalMenu(app, MenuDisplay("second", "Second"))
    assert first.content_panels[0].content is created[0]
    assert second.content_panels[0].content is created[1]
    assert created[0] is not created[1]


def test_global_content_and_factory_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="global_content.*global_content_factory"):
        TerminalApp(
            "App",
            ScreenContent.static("Content"),
            global_content_factory=lambda: ScreenContent.static("Other"),
        )


def test_one_stream_cannot_be_mounted_by_two_panels_in_the_same_application() -> None:
    def chunks() -> Iterator[str]:
        yield "One"

    menu = make_menu()
    content = ScreenContent.stream(chunks())
    first = menu.add_content_panel(content)
    with pytest.raises(ValueError, match="stream.*panel"):
        menu.add_content_panel(content)
    assert menu.content_panels == (first,)


def test_output_task_start_name_enforces_the_existing_lifecycle_contract() -> None:
    menu = make_menu()
    with pytest.raises(RuntimeError, match="active"):
        menu.start_output_task(
            lambda: 42, on_success=lambda result: None, on_error=lambda error: None
        )


def test_removed_stream_panels_do_not_retain_history_or_ownership() -> None:
    import gc
    import weakref

    menu = make_menu()
    content = ScreenContent.stream(iter(["One"]))
    panel = menu.add_content_panel(content)
    panel_reference = weakref.ref(panel)
    panel.remove()
    del panel
    gc.collect()
    assert panel_reference() is None
    assert len(menu.app._stream_owners) == 0
    assert menu.add_content_panel(content).content is content


def test_replacing_an_unstarted_stream_releases_its_previous_claim() -> None:
    menu = make_menu()
    previous = ScreenContent.stream(iter(["One"]))
    panel = menu.add_content_panel(previous)
    panel.set_content(ScreenContent.stream(iter(["Two"])))
    assert menu.add_content_panel(previous).content is previous


def test_invalid_choice_callback_does_not_insert_a_handle() -> None:
    menu = make_menu()
    with pytest.raises(TypeError, match="on_select"):
        menu.add_choice("Mode", [ChoiceOption("One")], None)  # type: ignore[arg-type]
    assert menu.commands == ()
