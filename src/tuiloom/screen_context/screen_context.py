from dataclasses import dataclass


@dataclass
class ScreenContext:
    """Store the user-configurable display state for one menu.

    Attributes:
        menu_name: Internal name used by contextual messages.
        title: Heading displayed in the menu box.
        width: Minimum inner width, or ``None`` for content-based sizing.
        text: Optional descriptive text above selectable commands.
        message: Optional footer message.
    """

    menu_name: str
    title: str
    width: int | None = None
    text: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        """Validate the minimum width eagerly."""
        self._validate_width(self.width)

    def __setattr__(self, name: str, value: object) -> None:
        """Validate width replacements as eagerly as construction."""
        if name == "width":
            self._validate_width(value)
        super().__setattr__(name, value)

    @staticmethod
    def _validate_width(value: object) -> None:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
        ):
            raise ValueError("ScreenContext.width must be a positive integer or None")
