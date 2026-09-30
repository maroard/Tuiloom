"""Describe deterministic, time-based animation frames and text sources."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import floor, isfinite
from numbers import Real


@dataclass(frozen=True, slots=True)
class AnimationFrame:
    """One animation sample on a menu's active-time timeline.

    ``elapsed`` excludes time while the menu is covered. ``index`` is the
    source's zero-based frame number, calculated from ``elapsed`` and its
    configured rate; skipped frames are not replayed. All sources on one menu
    share ``elapsed`` but can have different indices.
    """

    elapsed: float
    index: int


class TickHandle:
    """Cancel a periodic menu callback. Cancellation is idempotent."""

    def __init__(
        self,
        callback: Callable[[AnimationFrame], None],
        fps: float,
        remove: Callable[[TickHandle], None],
    ) -> None:
        self.callback = callback
        self.fps = fps
        self.last_index: int | None = None
        self.cancelled = False
        self._remove = remove

    def cancel(self) -> None:
        if not self.cancelled:
            self.cancelled = True
            self._remove(self)


def validate_fps(fps: float) -> float:
    """Validate a requested animation rate and return it as a float."""
    if isinstance(fps, bool) or not isinstance(fps, Real):
        raise TypeError("fps must be a finite real number")
    rate = float(fps)
    if not isfinite(rate) or not 0 < rate <= 60:
        raise ValueError("fps must be finite and between 0 and 60")
    return rate


class AnimatedText(str):
    """A string fallback with a frame renderer for visible menu text.

    Pass an instance in place of a menu title, description, footer message,
    command label, or choice-option label. Outside rendering it acts as the
    supplied ``fallback`` string, preserving existing label APIs. During menu
    rendering, Tuiloom calls ``renderer(frame)`` on the UI thread at most once
    per source and frame index. It must return a string promptly. The result
    is sanitized and measured like ordinary menu text. ``fps`` is a finite
    maximum rate in ``(0, 60]``, defaulting to 12.
    """

    __slots__ = ("renderer", "fps")
    renderer: Callable[[AnimationFrame], str]
    fps: float

    def __new__(
        cls,
        fallback: str,
        renderer: Callable[[AnimationFrame], str],
        *,
        fps: float = 12,
    ) -> AnimatedText:
        if not isinstance(fallback, str):
            raise TypeError("AnimatedText fallback must be a str")
        if not callable(renderer):
            raise TypeError("AnimatedText renderer must be callable")
        value = str.__new__(cls, fallback)
        object.__setattr__(value, "renderer", renderer)
        object.__setattr__(value, "fps", validate_fps(fps))
        return value

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("AnimatedText is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("AnimatedText is immutable")


type TextSource = str


class AnimationTimeline:
    """Track monotonic active time while a menu is visible at stack top."""

    def __init__(self, started_at: float) -> None:
        self._started_at = started_at
        self._paused_at: float | None = None
        self._paused_total = 0.0

    def set_active(self, active: bool, now: float) -> None:
        """Pause or resume the timeline without jumping its active phase."""
        if active:
            if self._paused_at is not None:
                self._paused_total += now - self._paused_at
                self._paused_at = None
        elif self._paused_at is None:
            self._paused_at = now

    def elapsed(self, now: float) -> float:
        """Return non-negative active seconds since menu runtime creation."""
        endpoint = self._paused_at if self._paused_at is not None else now
        return max(0.0, endpoint - self._started_at - self._paused_total)


_RAINBOW_STOPS = (
    (255, 0, 0),
    (255, 127, 0),
    (255, 255, 0),
    (0, 255, 0),
    (0, 0, 255),
    (75, 0, 130),
    (143, 0, 255),
)


def rainbow_color(elapsed: float, *, period: float = 2.1) -> tuple[int, int, int]:
    """Return a smoothly cycling RGB rainbow color for active elapsed time.

    The seven stops are red, orange, yellow, green, blue, indigo and violet.
    ``period`` is the duration in seconds of one complete, seamless cycle.
    Both numbers must be finite; elapsed must be non-negative and period must
    be positive. Pass the returned tuple to ``style(foreground=...)`` or
    ``style(background=...)`` inside an animation renderer.
    """
    if isinstance(elapsed, bool) or not isinstance(elapsed, Real):
        raise TypeError("elapsed must be a finite non-negative real number")
    if isinstance(period, bool) or not isinstance(period, Real):
        raise TypeError("period must be a finite positive real number")
    elapsed = float(elapsed)
    period = float(period)
    if not isfinite(elapsed) or elapsed < 0:
        raise ValueError("elapsed must be finite and non-negative")
    if not isfinite(period) or period <= 0:
        raise ValueError("period must be finite and positive")
    position = (elapsed % period) / period * len(_RAINBOW_STOPS)
    index = floor(position)
    fraction = position - index
    start = _RAINBOW_STOPS[index]
    end = _RAINBOW_STOPS[(index + 1) % len(_RAINBOW_STOPS)]
    return tuple(round(a + (b - a) * fraction) for a, b in zip(start, end, strict=True))
