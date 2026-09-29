"""Independent input and alert states; alerts can suspend active input."""

from dataclasses import dataclass

from tuiloom.command import CommandCallback, InputCallback


@dataclass(slots=True)
class InputState:
    """Keep a complete input session together until it is explicitly closed."""

    prompt: str
    callback: InputCallback
    hidden: bool = False
    buffer: str = ""


@dataclass(frozen=True, slots=True)
class AlertState:
    """Describe an alert independently of any suspended input session."""

    text: str
    on_confirm: CommandCallback | None
    prompt: str | None
