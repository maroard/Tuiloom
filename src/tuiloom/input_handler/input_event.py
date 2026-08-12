from dataclasses import dataclass
from typing import Literal

type InputEventType = Literal[
    "char", "enter", "backspace", "up", "down", "left", "right", "ctrl_c", "escape"
]


@dataclass
class InputEvent:
    """Represent one normalized terminal input event."""

    type: InputEventType
    value: str | None
