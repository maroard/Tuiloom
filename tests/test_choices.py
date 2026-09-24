from __future__ import annotations

import pytest

from tuiloom import (
    ChoiceOption,
    KeyBinding,
    ScreenContent,
    ScreenContext,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_text import display_width


def menu() -> TerminalMenu:
    app = TerminalApp("App")
    return TerminalMenu(app, ScreenContext("main", "Main"))


def press(target: TerminalMenu, key: str) -> None:
    target._handle_event(InputEvent(KeyBinding(key), None))


def test_choice_hover_and_deferred_selection() -> None:
    target = menu()
    events: list[tuple[str, int | None]] = []
    choice = target.add_choice(
        "Simulation mode",
        [
            ChoiceOption("Fast", on_hover=lambda c: events.append(("fast", c.index))),
            ChoiceOption(
                "Accurate", on_hover=lambda c: events.append(("accurate", c.index))
            ),
        ],
        lambda c: events.append(("select", c.index)),
        on_hover=lambda c: events.append(("label", None)),
    )
    target._prepare_open()
    assert events == [("label", None)]
    press(target, "enter")
    assert target._choice_index == 0
    assert choice.value == "Fast"
    assert events[-1] == ("fast", 0)
    press(target, "right")
    assert choice.value == "Fast"
    assert events[-1] == ("accurate", 1)
    count = len(events)
    press(target, "right")
    assert len(events) == count
    rendered = MenuRenderer(target).render()
    assert "✓ Fast" in rendered
    assert "> Accurate" in rendered
    assert ">   Accurate" not in rendered
    press(target, "enter")
    assert choice.value == "Accurate"
    assert events[-1] == ("select", 1)
    press(target, "enter")
    assert events[-1] == ("select", 1)
    press(target, "left")
    press(target, "left")
    assert events.count(("label", None)) == 2


def test_leftmost_option_cursor_is_indented_and_check_has_one_space() -> None:
    target = menu()
    target.add_choice(
        "Mode",
        [ChoiceOption("Fast"), ChoiceOption("Accurate")],
        lambda c: None,
        selected_index=1,
    )
    target._prepare_open()
    press(target, "right")
    assert "│  > Fast" in MenuRenderer(target).render()
    press(target, "enter")
    assert "│  > ✓ Fast" in MenuRenderer(target).render()


def test_validating_right_option_keeps_cursor_column_fixed() -> None:
    target = menu()
    target.add_choice(
        "Mode", [ChoiceOption("Fast"), ChoiceOption("Accurate")], lambda c: None
    )
    target._prepare_open()
    press(target, "right")
    press(target, "right")
    before = next(
        line
        for line in MenuRenderer(target).render().splitlines()
        if "> Accurate" in line
    )
    cursor_column = before.index(">")
    press(target, "enter")
    after = next(
        line
        for line in MenuRenderer(target).render().splitlines()
        if "> ✓ Accurate" in line
    )
    assert after.index(">") == cursor_column
    assert after.index("Accurate") == before.index("Accurate") + 2


def test_visual_rows_and_resize_drive_navigation() -> None:
    target = menu()
    choice = target.add_choice(
        "Mode",
        [ChoiceOption("Alpha"), ChoiceOption("Beta"), ChoiceOption("Gamma", row=2)],
        lambda c: None,
        rows=3,
    )
    target.add_command("Next", lambda c: None)
    target._prepare_open()
    renderer = MenuRenderer(target)
    target.screen_context.width = 25
    target.screen_context.strict_width = True
    press(target, "right")
    press(target, "down")
    assert target._choice_index == 2
    press(target, "down")
    assert target._selected_index == 1
    assert target._choice_index is None
    press(target, "up")
    assert target._selected_index == choice.position
    target.screen_context.width = 12
    press(target, "right")
    press(target, "down")
    assert target._choice_index == 1
    assert "│  > Beta" in renderer.render()
    assert all(display_width(line) == 14 for line in renderer.render().splitlines())


def test_choice_mutations_and_validation() -> None:
    target = menu()
    with pytest.raises(ValueError):
        target.add_choice("Empty", [], lambda c: None)
    with pytest.raises(ValueError):
        target.add_choice("Rows", [ChoiceOption("One", row=1)], lambda c: None)
    with pytest.raises(ValueError):
        target.add_choice(
            "Index", [ChoiceOption("One")], lambda c: None, selected_index=1
        )
    choice = target.add_choice(
        "Mode", [ChoiceOption("One"), ChoiceOption("Two")], lambda c: None
    )
    target.set_choice_value(choice, 1)
    assert choice.value == "Two"
    assert choice.selected_index == 1
    target.set_command_label(choice, "Renamed")
    target.disable_command(choice)
    assert not choice.enabled
    target.enable_command(choice)
    target.move_command(choice, 0)
    assert choice.label == "Renamed"
    with pytest.raises(ValueError):
        target.set_choice_value(choice, 3)


def test_choice_callback_can_be_replaced_through_command_mutation() -> None:
    target = menu()
    calls: list[str] = []
    choice = target.add_choice(
        "Mode", [ChoiceOption("One")], lambda c: calls.append("old")
    )
    target.set_command_behavior(choice, lambda c: calls.append(c.option.label))
    target._prepare_open()
    press(target, "enter")
    press(target, "enter")
    assert calls == ["One"]


def test_ordinary_hover_fires_on_arrival_only() -> None:
    target = menu()
    calls: list[str] = []
    target.add_command(
        "First", lambda c: None, on_hover=lambda c: calls.append("first")
    )
    target.add_command(
        "Second", lambda c: None, on_hover=lambda c: calls.append("second")
    )
    target._prepare_open()
    press(target, "right")
    press(target, "down")
    press(target, "up")
    assert calls == ["first", "second", "first"]


def test_command_hover_receives_triggering_binding() -> None:
    target = menu()
    bindings: list[KeyBinding | None] = []
    target.add_command("First", lambda c: None)
    target.add_command(
        "Second", lambda c: None, on_hover=lambda c: bindings.append(c.binding)
    )
    target._prepare_open()
    press(target, "down")
    assert bindings == [KeyBinding("down")]


def test_submenu_command_can_hover_before_activation() -> None:
    target = menu()
    child = TerminalMenu(target.app, ScreenContext("child", "Child"))
    calls: list[str] = []
    target.add_menu(child, "Open", on_hover=lambda c: calls.append("hover"))
    target._prepare_open()
    assert calls == ["hover"]


def test_down_from_choice_label_skips_options_and_right_uses_row_order() -> None:
    target = menu()
    target.add_choice(
        "Mode",
        [ChoiceOption("Later", row=1), ChoiceOption("First", row=0)],
        lambda c: None,
        rows=2,
    )
    target.add_command("Next", lambda c: None)
    target._prepare_open()
    press(target, "down")
    assert target._selected_index == 1
    assert target._choice_index is None
    assert "First" not in MenuRenderer(target).render()
    press(target, "up")
    assert target._selected_index == 0
    press(target, "right")
    assert target._choice_index == 1
    press(target, "right")
    assert target._choice_index == 0
    press(target, "up")
    assert target._choice_index == 1
    press(target, "up")
    assert target._choice_index is None


def test_long_option_wraps_without_becoming_multiple_targets() -> None:
    target = menu()
    target.screen_context.width = 6
    target.screen_context.strict_width = True
    target.add_choice(
        "Mode", [ChoiceOption("abcdefghij"), ChoiceOption("Next")], lambda c: None
    )
    target._prepare_open()
    press(target, "right")
    rendered = MenuRenderer(target).render()
    assert "abcdefghij" in "".join(line[1:-1].strip() for line in rendered.splitlines())
    assert all(display_width(line) == 8 for line in rendered.splitlines())
    press(target, "down")
    assert target._choice_index == 1


@pytest.mark.parametrize("width", [1, 2, 3])
def test_choice_keeps_exact_strict_width(width: int) -> None:
    target = menu()
    target.screen_context.width = width
    target.screen_context.strict_width = True
    target.add_choice(
        "Mode", [ChoiceOption("界a"), ChoiceOption("Other")], lambda c: None
    )
    target._prepare_open()
    press(target, "right")
    lines = MenuRenderer(target).render().splitlines()
    assert all(display_width(line) == width + 2 for line in lines)
    assert sum(">" in line for line in lines) == 1
    press(target, "right")
    assert target._choice_index == 1


def test_hover_message_overlays_without_mutating_persistent_message() -> None:
    target = menu()
    target.app.add_message("one", "First preview")
    target.app.add_message("two", "Second preview")
    target.app.add_message("persistent", "Saved footer")
    target.show_message("persistent")
    target.add_choice(
        "Mode",
        [
            ChoiceOption("First", hover_message="one"),
            ChoiceOption("Second", hover_message="two"),
        ],
        lambda c: None,
    )
    target._prepare_open()
    renderer = MenuRenderer(target)
    assert "Saved footer" in renderer.render()
    press(target, "right")
    assert "First preview" in renderer.render()
    assert "Saved footer" not in renderer.render()
    assert target.screen_context.message == "Saved footer"
    assert target.active_message_key == "persistent"
    press(target, "right")
    assert "Second preview" in renderer.render()
    press(target, "left")
    press(target, "left")
    assert "Saved footer" in renderer.render()
    assert "First preview" not in renderer.render()


def test_hover_message_disappears_on_next_command_and_content_focus() -> None:
    app = TerminalApp("App")
    app.add_message("preview", "Temporary preview")
    target = TerminalMenu(
        app, ScreenContext("main", "Main"), content=ScreenContent.static("Panel")
    )
    target.add_choice(
        "Mode", [ChoiceOption("First", hover_message="preview")], lambda c: None
    )
    target.add_command("Next", lambda c: None)
    target._prepare_open()
    renderer = MenuRenderer(target)
    press(target, "right")
    assert "Temporary preview" in renderer.render()
    press(target, "tab")
    assert "Temporary preview" not in renderer.render()
    press(target, "tab")
    assert "Temporary preview" in renderer.render()
    press(target, "down")
    assert "Temporary preview" not in renderer.render()
    target._prepare_open()
    assert "Temporary preview" not in renderer.render()


def test_hover_message_rejects_unknown_registered_key() -> None:
    target = menu()
    with pytest.raises(KeyError):
        target.add_choice(
            "Mode", [ChoiceOption("First", hover_message="missing")], lambda c: None
        )
    assert target.commands == ()


def test_deleting_active_choice_resets_option_cursor() -> None:
    target = menu()
    first = target.add_choice(
        "First",
        [ChoiceOption("One"), ChoiceOption("Two")],
        lambda c: None,
    )
    target.add_choice("Second", [ChoiceOption("Only")], lambda c: None)
    target._prepare_open()
    press(target, "right")
    press(target, "right")
    target.delete_command(first)
    assert target._choice_index is None
    assert "Only" in MenuRenderer(target).render()
