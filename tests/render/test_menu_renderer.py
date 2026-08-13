from typing import Any

from tuiloom.command import CommandContext
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_text import display_width
from tuiloom.screen_context.screen_context import ScreenContext


def do_nothing(context: CommandContext) -> None:
    """Provide a command behavior for menu renderer tests."""


def make_context(**changes: object) -> ScreenContext:
    """Build a context with defaults that tests can selectively replace."""
    values: dict[str, Any] = {
        "app_name": "App",
        "menu_name": "Menu",
        "title": "Title",
        "commands": {"0": (do_nothing, "Back")},
    }
    values.update(changes)
    return ScreenContext(**values)


def test_update_screen_context_replaces_every_rendered_field() -> None:
    renderer = MenuRenderer(make_context(width=20))
    commands = {
        "0": (do_nothing, "Quit"),
        "1": (do_nothing, "Generate"),
    }
    context = make_context(
        app_name="New App",
        title="New Title",
        width=42,
        commands=commands,
        text="Description",
        two_columns=True,
        message="Credits",
        alert="Warning",
        prompt="Continue: ",
    )

    renderer.update_screen_context(context)

    assert renderer.app_name == "New App"
    assert renderer.title == "New Title"
    assert renderer.width == 42
    assert renderer.commands is commands
    assert renderer.text == "Description"
    assert renderer.two_columns is True
    assert renderer.message == "Credits"
    assert renderer.alert == "Warning"
    assert renderer.prompt == "Continue: "
    assert "Credits" in renderer._get_message_display()


def test_update_screen_context_recalculates_automatic_width() -> None:
    renderer = MenuRenderer(make_context(width=None))
    context = make_context(width=None, message="A much longer message")

    renderer.update_screen_context(context)

    assert renderer.width == len("A much longer message") + 2


def visible_lines(render: str) -> list[str]:
    return render.split("\n")


def test_automatic_width_ignores_sgr_and_counts_wide_text() -> None:
    renderer = MenuRenderer(
        make_context(
            app_name="\x1b[31m界界\x1b[0m",
            title="e\u0301",
            width=None,
            commands={"0": (do_nothing, "Q")},
        )
    )

    assert renderer.width == 5


def test_every_box_row_keeps_the_same_visible_width() -> None:
    renderer = MenuRenderer(
        make_context(
            width=20,
            app_name="\x1b[31mApp界\x1b[0m",
            title="\x1b[1mTitle\x1b[0m",
            text="Text 👨‍👩‍👧",
            message="\x1b[38;5;200mMessage\x1b[0m",
            commands={
                "0": (do_nothing, "Quit"),
                "1": (do_nothing, "\x1b[32mGenerate界\x1b[0m"),
            },
        )
    )

    boxed = [
        line
        for line in visible_lines(renderer.render())
        if line.startswith(("│", "├", "╭", "╰"))
    ]

    assert {display_width(line) for line in boxed} == {22}


def test_two_column_commands_align_with_styled_wide_labels() -> None:
    renderer = MenuRenderer(
        make_context(
            width=30,
            two_columns=True,
            commands={
                "0": (do_nothing, "Quit"),
                "1": (do_nothing, "\x1b[31m界\x1b[0m"),
                "2": (do_nothing, "Emoji 👨‍👩‍👧"),
            },
        )
    )

    assert all(
        display_width(line) == 32
        for line in visible_lines(renderer.render())
        if line.startswith("│")
    )


def test_wrapping_preserves_sgr_and_unicode_boundaries() -> None:
    renderer = MenuRenderer(
        make_context(width=8, text="\x1b[34m界界 界界\x1b[0m")
    )

    wrapped = renderer._wrap_lines(renderer.text or "")

    assert all(display_width(line) <= 6 for line in wrapped)
    assert all("\x1b[34m" in line for line in wrapped)


def test_styled_unicode_prompt_keeps_its_visible_text() -> None:
    renderer = MenuRenderer(
        make_context(width=20, prompt="\x1b[36mChoix界: \x1b[0m")
    )

    prompt = renderer._get_prompt_display()

    assert display_width(prompt) == 9
    assert "\x1b[36m" in prompt


def test_unchanged_screen_context_reuses_cached_menu_render() -> None:
    context = make_context(width=20)
    renderer = MenuRenderer(context)

    first = renderer.render()
    renderer.update_screen_context(context)
    second = renderer.render()

    assert second is first


def test_changed_screen_context_invalidates_cached_menu_render() -> None:
    context = make_context(width=20, message="first")
    renderer = MenuRenderer(context)
    first = renderer.render()

    context.message = "second"
    renderer.update_screen_context(context)

    assert renderer.render() != first
