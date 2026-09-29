"""Define the live, mutable appearance settings retained by a terminal menu.

``MenuDisplay`` controls the menu box in both inline and overlay presentations.
Presentation and box visibility are configured on ``TerminalMenu`` itself;
callback execution metadata is supplied separately through ``CommandContext``.
"""

from dataclasses import dataclass, field


@dataclass
class MenuDisplay:
    """Store mutable menu appearance settings that are read on each UI frame.

    ``TerminalMenu`` retains this object by reference, so assigning its fields
    changes the next rendered frame. Text wraps to fit the configured inner
    width. A width that cannot fit the terminal produces the terminal-too-small
    display rather than overriding the minimum.

    These sizing rules also apply to overlay menus. Overlay presentation centers
    the box over the content area, reserving no panel rows for the box or its
    spacing; an installed status bar still reserves its own bottom row. Use
    ``TerminalMenu`` presentation and visibility settings to choose or hide the
    box; this object does not control navigation or callback execution.

    Attributes:
        menu_name: Mutable ``str`` name used in contextual messages, independent
            of global menu identity; need not be globally unique. Has no default.
        title: Mutable ``str`` heading displayed in the menu box; has no default.
        width: Mutable positive ``int`` inner width in terminal cells, excluding
            borders, or ``None`` for automatic sizing. Defaults to ``None``;
            bool values are rejected. It is a minimum unless ``strict_width`` is
            true. Invalid assignments leave the previous value unchanged.
        text: Mutable ``str`` descriptive text above commands, or ``None`` by
            default. Text can span multiple lines and wraps to the inner width.
        message: Mutable ``str`` persistent footer text, or ``None`` by default.
            Option hover previews may temporarily cover it without changing it.
            Assignment clears a registered message's identity, even when the
            visible text is unchanged. Use ``menu.show_message()`` to retain a
            registered message key.
        strict_width: Mutable ``bool`` making ``width`` fixed rather than a
            minimum. Defaults to ``False``; has no effect with ``width=None``.
            Invalid assignments leave the previous value unchanged.

    Raises:
        ValueError: If ``width`` is neither ``None`` nor a positive integer,
            including a bool. Applies during construction and assignment.
        TypeError: If ``strict_width`` is not a bool, during construction or
            assignment.
    """

    menu_name: str
    title: str
    width: int | None = None
    text: str | None = None
    message: str | None = None
    strict_width: bool = False
    _active_message_key: str | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __setattr__(self, name: str, value: object) -> None:
        if name == "width":
            self._validate_width(value)
        elif name == "strict_width" and not isinstance(value, bool):
            raise TypeError("MenuDisplay.strict_width must be a bool")
        elif name == "message":
            super().__setattr__("_active_message_key", None)
        super().__setattr__(name, value)

    def _set_registered_message(self, key: str, text: str) -> None:
        """Install resolved footer text together with its registry identity."""
        self.message = text
        self._active_message_key = key

    @staticmethod
    def _validate_width(value: object) -> None:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
        ):
            raise ValueError("MenuDisplay.width must be a positive integer or None")
