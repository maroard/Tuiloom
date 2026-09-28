"""Lightweight descriptions of one current-state terminal line."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True, init=False)
class StatusBar:
    """Describe a fixed, dynamic, or width-responsive status line.

    Producers run in the UI loop and must be fast and non-blocking: read
    application state and return a string, without I/O or expensive work.
    """

    _kind: Literal["static", "dynamic", "responsive"]
    _producer: Callable[[int], str]

    def __init__(self) -> None:
        raise TypeError("Use a named StatusBar factory")

    @classmethod
    def _create(
        cls,
        kind: Literal["static", "dynamic", "responsive"],
        producer: Callable[[int], str],
    ) -> StatusBar:
        status = object.__new__(cls)
        object.__setattr__(status, "_kind", kind)
        object.__setattr__(status, "_producer", producer)
        return status

    @classmethod
    def static(cls, text: str) -> StatusBar:
        """Create a status line from a fixed string."""
        if not isinstance(text, str):
            raise TypeError("StatusBar.static() requires a str")
        return cls._create("static", lambda width: text)

    @classmethod
    def dynamic(cls, renderer: Callable[[], str]) -> StatusBar:
        """Evaluate a lightweight renderer on scheduled UI frames, up to 60 Hz."""
        if not callable(renderer):
            raise TypeError("StatusBar.dynamic() requires a callable")
        return cls._create("dynamic", lambda width: renderer())

    @classmethod
    def responsive(cls, renderer: Callable[[int], str]) -> StatusBar:
        """Render on installation, width changes, or explicit menu refresh."""
        if not callable(renderer):
            raise TypeError("StatusBar.responsive() requires a callable")
        return cls._create("responsive", renderer)
