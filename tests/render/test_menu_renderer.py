from tuiloom.command import CommandContext
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.screen_context.screen_context import ScreenContext


def do_nothing(context: CommandContext) -> None:
    """Provide a command behavior for menu renderer tests."""


def make_context(**changes: object) -> ScreenContext:
    """Build a context with defaults that tests can selectively replace."""
    values = {
        "app_name": "App",
        "menu_name": "Menu",
        "title": "Title",
        "commands": {"0": (do_nothing, "Back")},
    }
    values.update(changes)
    return ScreenContext(**values)  # type: ignore[arg-type]


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
