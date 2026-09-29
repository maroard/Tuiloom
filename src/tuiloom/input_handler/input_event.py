from dataclasses import dataclass

from tuiloom.key_binding import KeyBinding


@dataclass(frozen=True, slots=True)
class InputEvent:
    """Represent a decoded key or terminal focus notification."""

    binding: KeyBinding | None
    text: str | None = None
    terminal_focus: bool | None = None
