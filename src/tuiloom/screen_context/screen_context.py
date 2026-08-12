from dataclasses import dataclass, field

from tuiloom.command import CommandDict


@dataclass
class ScreenContext:
    """Store the user-configurable display state consumed by menu renderers.

    Attributes:
        app_name: Application name displayed by the menu.
        menu_name: Internal menu name used in contextual messages.
        title: Heading displayed at the top of the menu.
        width: Inner menu width, or ``None`` for automatic sizing.
        commands: Commands indexed by their selection text.
        text: Optional descriptive text displayed above commands.
        two_columns: Whether commands are arranged in two columns.
        message: Optional informational message displayed in the footer.
        alert: Optional alert that replaces the normal menu body.
        prompt: Optional replacement for the default input prompt.
        show_menu: Whether the menu is intended to be displayed.
    """

    app_name: str
    menu_name: str
    title: str
    width: int | None = None
    commands: CommandDict = field(default_factory=dict)
    text: str | None = None
    two_columns: bool = False
    message: str | None = None
    alert: str | None = None
    prompt: str | None = None
    show_menu: bool = True
