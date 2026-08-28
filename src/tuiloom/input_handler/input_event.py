from dataclasses import dataclass

from tuiloom.key_binding import KeyBinding


@dataclass(frozen=True, slots=True)
class InputEvent:
    """Represent one normalized Blessed keyboard event."""

    binding: KeyBinding | None
    text: str | None = None
