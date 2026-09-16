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
        strict_width: Fix the inner width when ``width`` is provided.
    """

    menu_name: str
    title: str
    width: int | None = None
    text: str | None = None
    message: str | None = None
    strict_width: bool = False

    def __post_init__(self) -> None:
        """Validate the minimum width eagerly."""
        self._validate_width(self.width)

    def __setattr__(self, name: str, value: object) -> None:
        """Validate sizing replacements as eagerly as construction."""
        if name == "width":
            self._validate_width(value)
        elif name == "strict_width" and not isinstance(value, bool):
            raise TypeError("ScreenContext.strict_width must be a bool")
        super().__setattr__(name, value)

    @staticmethod
    def _validate_width(value: object) -> None:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
        ):
            raise ValueError("ScreenContext.width must be a positive integer or None")
