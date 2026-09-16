"""Explicit descriptions of content rendered in a terminal panel."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal, cast

type ContentRefreshMode = Literal["resize", "continuous"]
type ContentValue = str | list[str]
type ContentKind = Literal["static", "lines", "stream", "dynamic", "responsive"]
type ContentProducer = (
    str
    | tuple[str, ...]
    | Iterator[str]
    | Callable[[], ContentValue]
    | Callable[[ContentSize], ContentValue]
)


@dataclass(frozen=True, slots=True)
class ContentSize:
    """Virtual width and height available to a responsive renderer."""

    width: int
    height: int


@dataclass(frozen=True, slots=True, init=False)
class ScreenContent:
    """Describe how a content panel produces text.

    Instances are deliberately created through the named factories so the
    runtime never needs to infer a callable's purpose from its signature.
    """

    _kind: ContentKind
    _producer: ContentProducer
    min_width: int | None
    min_height: int | None
    refresh_mode: ContentRefreshMode | None

    def __init__(self) -> None:
        raise TypeError("Use a named ScreenContent factory")

    @classmethod
    def _create(
        cls,
        kind: ContentKind,
        producer: ContentProducer,
        *,
        min_width: int | None = None,
        min_height: int | None = None,
        refresh_mode: ContentRefreshMode | None = None,
    ) -> ScreenContent:
        content = object.__new__(cls)
        object.__setattr__(content, "_kind", kind)
        object.__setattr__(content, "_producer", producer)
        object.__setattr__(content, "min_width", min_width)
        object.__setattr__(content, "min_height", min_height)
        object.__setattr__(content, "refresh_mode", refresh_mode)
        return content

    @classmethod
    def static(cls, text: str) -> ScreenContent:
        """Create content from one fixed string."""
        if not isinstance(text, str):
            raise TypeError("ScreenContent.static() requires a str")
        return cls._create("static", text)

    @classmethod
    def lines(cls, lines: list[str]) -> ScreenContent:
        """Create content from an immutable copy of fixed lines."""
        if not isinstance(lines, list) or not all(
            isinstance(line, str) for line in lines
        ):
            raise TypeError("ScreenContent.lines() requires a list[str]")
        return cls._create("lines", tuple(lines))

    @classmethod
    def stream(cls, iterator: Iterator[str]) -> ScreenContent:
        """Create content from an iterator consumed exactly once."""
        if not isinstance(iterator, Iterator):
            raise TypeError("ScreenContent.stream() requires an Iterator[str]")
        return cls._create("stream", iterator)

    @classmethod
    def dynamic(cls, renderer: Callable[[], ContentValue]) -> ScreenContent:
        """Create content evaluated repeatedly, at most sixty times a second."""
        if not callable(renderer):
            raise TypeError("ScreenContent.dynamic() requires a callable")
        return cls._create("dynamic", renderer)

    @classmethod
    def responsive(
        cls,
        renderer: Callable[[ContentSize], ContentValue],
        *,
        min_width: int | None = None,
        min_height: int | None = None,
        refresh_mode: ContentRefreshMode = "resize",
    ) -> ScreenContent:
        """Create content rendered for the panel's effective virtual size."""
        if not callable(renderer):
            raise TypeError("ScreenContent.responsive() requires a callable")
        cls._validate_minimum("min_width", min_width)
        cls._validate_minimum("min_height", min_height)
        if refresh_mode not in ("resize", "continuous"):
            raise ValueError("refresh_mode must be 'resize' or 'continuous'")
        return cls._create(
            "responsive",
            renderer,
            min_width=min_width,
            min_height=min_height,
            refresh_mode=refresh_mode,
        )

    @staticmethod
    def _validate_minimum(name: str, value: int | None) -> None:
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be a positive integer or None")
        if value <= 0:
            raise ValueError(f"{name} must be a positive integer or None")

    def _static_value(self) -> str | tuple[str, ...]:
        return cast(str | tuple[str, ...], self._producer)

    def _stream(self) -> Iterator[str]:
        return cast(Iterator[str], self._producer)

    def _dynamic(self) -> Callable[[], ContentValue]:
        return cast(Callable[[], ContentValue], self._producer)

    def _responsive(self) -> Callable[[ContentSize], ContentValue]:
        return cast(Callable[[ContentSize], ContentValue], self._producer)
