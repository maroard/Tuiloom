from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

_SYSTEM_ACTIONS = ("focus", "up", "down", "left", "right", "activate", "back")
_SPECIAL_ALIASES = {
    "return": "enter",
    "esc": "escape",
    "arrow_up": "up",
    "arrow_down": "down",
    "arrow_left": "left",
    "arrow_right": "right",
}


@dataclass(frozen=True, slots=True)
class KeyBinding:
    """Identify a key and the modifiers required to invoke an action.

    Attributes:
        key: A printable key or normalized special-key name such as ``"enter"``.
        ctrl: Whether Control must be held.
        alt: Whether Alt must be held.
        shift: Whether Shift must be held.

    Terminal protocols do not always report every modifier. In particular,
    Ctrl+letter is commonly case-insensitive and Shift+letter may arrive only as
    an uppercase character.
    """

    key: str
    ctrl: bool = False
    alt: bool = False
    shift: bool = False

    def __post_init__(self) -> None:
        """Validate and normalize the key name without changing its meaning."""
        if not isinstance(self.key, str) or not self.key:
            raise ValueError("A key binding must contain a nonempty string key")
        if not all(
            isinstance(value, bool) for value in (self.ctrl, self.alt, self.shift)
        ):
            raise TypeError("Key binding modifiers must be bool values")

        normalized = _SPECIAL_ALIASES.get(self.key.lower(), self.key)
        if len(normalized) > 1:
            normalized = normalized.lower()
        object.__setattr__(self, "key", normalized)


class KeyMap:
    """Configure the system bindings used for focus and navigation.

    Attributes:
        bindings: Read-only action-to-binding mapping.
        focus: Binding that switches between menu and content focus.
        up: Binding that moves up in the focused zone.
        down: Binding that moves down in the focused zone.
        left: Binding that scrolls content left.
        right: Binding that scrolls content right.
        activate: Binding that activates the selected menu command.
        back: Binding that performs the automatic Back/Quit action.

    Use :meth:`set_binding` to mutate the map atomically. A collision raises
    ``ValueError`` and leaves the previous binding unchanged.
    """

    def __init__(self) -> None:
        """Create the default Tab, arrow, Enter, and Escape mapping."""
        self._bindings: dict[str, KeyBinding] = {
            "focus": KeyBinding("tab"),
            "up": KeyBinding("up"),
            "down": KeyBinding("down"),
            "left": KeyBinding("left"),
            "right": KeyBinding("right"),
            "activate": KeyBinding("enter"),
            "back": KeyBinding("escape"),
        }
        self._external_validator: Callable[[str, KeyBinding], None] | None = None

    @property
    def bindings(self) -> Mapping[str, KeyBinding]:
        """Return an immutable live view of all system bindings."""
        return MappingProxyType(self._bindings)

    def __getattr__(self, action: str) -> KeyBinding:
        if action in _SYSTEM_ACTIONS:
            return self._bindings[action]
        raise AttributeError(action)

    def set_binding(self, action: str, binding: KeyBinding) -> None:
        """Replace one action binding after checking every collision.

        Args:
            action: One of ``focus``, ``up``, ``down``, ``left``, ``right``,
                ``activate``, or ``back``.
            binding: New binding for that action.

        Raises:
            KeyError: If ``action`` is unknown.
            TypeError: If ``binding`` is not a :class:`KeyBinding`.
            ValueError: If another system or global command already uses it.
        """
        if action not in self._bindings:
            raise KeyError(f"Unknown key-map action: {action!r}")
        if not isinstance(binding, KeyBinding):
            raise TypeError("Key-map bindings must be KeyBinding instances")

        for other_action, other_binding in self._bindings.items():
            if other_action != action and other_binding == binding:
                raise ValueError(
                    f"Binding {binding!r} is already used by system action "
                    f"{other_action!r}"
                )
        if self._external_validator is not None:
            self._external_validator(action, binding)
        self._bindings[action] = binding

    def action_for(self, binding: KeyBinding) -> str | None:
        """Return the system action matching ``binding``, if any."""
        return next(
            (
                action
                for action, candidate in self._bindings.items()
                if candidate == binding
            ),
            None,
        )

    def _set_external_validator(
        self, validator: Callable[[str, KeyBinding], None] | None
    ) -> None:
        """Install the owning application's collision validator."""
        self._external_validator = validator
