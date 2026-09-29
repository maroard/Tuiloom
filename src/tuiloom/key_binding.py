"""Define immutable key descriptions and configurable navigation bindings.

``KeyBinding`` normalizes special-key aliases for equality comparisons.
``KeyMap`` stores the seven system actions separately from global commands; an
owning ``TerminalApp`` also checks global-command collisions on map mutations.

Attributes:
    KeyAction: Literal action name accepted by ``KeyMap``: ``"focus"``, ``"up"``,
        ``"down"``, ``"left"``, ``"right"``, ``"activate"``, or ``"back"``.
        Arrow actions navigate commands or choices when the menu is focused and
        scroll content when a content panel is focused.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

type KeyAction = Literal["focus", "up", "down", "left", "right", "activate", "back"]
"""One of the seven focus, navigation, activation, or cancellation action names."""

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
    """Identify an immutable key and its required modifiers.

    Single-character keys preserve their case. Multi-character key names become
    lowercase, and ``return``, ``esc``, and ``arrow_up/down/left/right`` normalize
    to ``enter``, ``escape``, and the corresponding direction. Key names are not
    checked against a fixed supported-key list. Equality includes all modifiers.

    Terminal protocols do not always report every modifier. In particular,
    Ctrl+letter is commonly case-insensitive and Shift+letter may arrive only as
    an uppercase character, so a binding must match what the terminal reports.

    Attributes:
        key: Read-only nonempty ``str`` containing a character or normalized
            special-key name, such as ``"enter"``; has no default.
        ctrl: Read-only ``bool`` indicating whether Control is required.
            Defaults to ``False``.
        alt: Read-only ``bool`` indicating whether Alt is required.
            Defaults to ``False``.
        shift: Read-only ``bool`` indicating whether Shift is required.
            Defaults to ``False``.

    Raises:
        ValueError: If ``key`` is not a string or is empty.
        TypeError: If any modifier is not a bool.
    """

    key: str
    ctrl: bool = False
    alt: bool = False
    shift: bool = False

    def __post_init__(self) -> None:
        """Validate construction and normalize aliases and multi-character names.

        Raises:
            ValueError: If ``key`` is not a nonempty string.
            TypeError: If a modifier is not a bool.
        """
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
    """Configure the seven system bindings used for keyboard navigation.

    Construction creates Tab for focus, arrow keys for directions, Enter for
    activation, and Escape for Back/Quit or mode cancellation. Properties expose
    read-only current bindings; use ``set_binding()`` to change them atomically.
    Duplicate system bindings are rejected, as are collisions with global
    commands when the map belongs to a ``TerminalApp``.

    A map can belong to one application. Passing an already owned map to another
    application raises ``ValueError``; use ``copy()`` to reuse its configuration
    with independent future mutations and no inherited application owner.

    Attributes:
        bindings: Read-only live mapping from ``KeyAction`` names to bindings.
        focus: Read-only binding for cycling menu and content-panel focus.
        up: Read-only binding for upward menu selection or panel scrolling.
        down: Read-only binding for downward menu selection or panel scrolling.
        left: Read-only binding for leftward option navigation or panel scrolling.
        right: Read-only binding for rightward option navigation or panel scrolling.
        activate: Read-only binding for command activation, option confirmation,
            input submission, or alert confirmation.
        back: Read-only binding for Back/Quit or cancellation of input mode.
    """

    def __init__(self) -> None:
        """Create independent default system bindings with no application owner.

        Defaults are Tab for ``focus``, the corresponding arrow keys for ``up``,
        ``down``, ``left`` and ``right``, Enter for ``activate``, and Escape for
        ``back``. A ``TerminalApp`` takes ownership when given this map and adds
        its global-command collision checks to subsequent ``set_binding()`` calls.
        """
        self._bindings: dict[KeyAction, KeyBinding] = {
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
    def bindings(self) -> Mapping[KeyAction, KeyBinding]:
        """Read every configured system binding without permitting direct mutation.

        Returns:
            A read-only live mapping from action names to ``KeyBinding`` objects,
            not a snapshot. Successful ``set_binding()`` calls are reflected in
            views already obtained from this property.
        """
        return MappingProxyType(self._bindings)

    @property
    def focus(self) -> KeyBinding:
        """Read the binding that cycles menu and content-panel focus.

        Returns:
            The current ``focus`` binding, initially ``KeyBinding("tab")``.
        """
        return self._bindings["focus"]

    @property
    def up(self) -> KeyBinding:
        """Read the binding for upward menu selection or focused-panel scrolling.

        Returns:
            The current ``up`` binding, initially ``KeyBinding("up")``.
        """
        return self._bindings["up"]

    @property
    def down(self) -> KeyBinding:
        """Read the binding for downward menu selection or focused-panel scrolling.

        Returns:
            The current ``down`` binding, initially ``KeyBinding("down")``.
        """
        return self._bindings["down"]

    @property
    def left(self) -> KeyBinding:
        """Read the binding for leftward choice navigation or panel scrolling.

        Returns:
            The current ``left`` binding, initially ``KeyBinding("left")``.
        """
        return self._bindings["left"]

    @property
    def right(self) -> KeyBinding:
        """Read the binding for rightward choice navigation or panel scrolling.

        Returns:
            The current ``right`` binding, initially ``KeyBinding("right")``.
        """
        return self._bindings["right"]

    @property
    def activate(self) -> KeyBinding:
        """Read the binding for activation, selection confirmation, or submission.

        Returns:
            The current ``activate`` binding, initially ``KeyBinding("enter")``.
            It activates commands, opens or confirms choices, submits input, and
            confirms alerts according to the menu's current interaction mode.
        """
        return self._bindings["activate"]

    @property
    def back(self) -> KeyBinding:
        """Read the binding for Back/Quit or input cancellation.

        Returns:
            The current ``back`` binding, initially ``KeyBinding("escape")``.
            Input mode cancels input with this action; normal and alert modes
            request the menu's Back/Quit behavior.
        """
        return self._bindings["back"]

    def copy(self) -> KeyMap:
        """Copy the bindings into an independent map with no application owner.

        A map can belong to one TerminalApp. Use this method to reuse its
        configuration in another app; later mutations remain independent.

        Returns:
            A new ``KeyMap`` containing the same immutable ``KeyBinding`` values
            in an independent mapping, without the original application's
            collision validator or ownership.
        """
        result = KeyMap()
        result._bindings = self._bindings.copy()
        return result

    def set_binding(self, action: KeyAction, binding: KeyBinding) -> None:
        """Replace one system binding atomically after checking collisions.

        The prior binding is retained if validation fails. When an application
        owns this map, its global-command registry participates in collision
        checks; an unowned copy checks only its own system bindings.

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

    def action_for(self, binding: KeyBinding) -> KeyAction | None:
        """Find the system action matching a key and all its modifiers.

        This performs a lookup without mutating the map or invoking any action.

        Args:
            binding: Key binding to compare with configured system bindings.

        Returns:
            The matching ``KeyAction`` name, or ``None`` if no system action has
            an equal binding. Global commands are not part of this lookup.
        """
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
        if validator is not None and self._external_validator is not None:
            raise ValueError("KeyMap already belongs to an application; use copy()")
        self._external_validator = validator
