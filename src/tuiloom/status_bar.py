"""Define immutable descriptions of a menu's bottom status line.

Create a ``StatusBar`` with a named factory, then install it with
``TerminalMenu.set_status_bar()``. Providers run synchronously during UI
rendering; they are suitable for reading current state, not producing logs or
performing background work.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from tuiloom.animation import AnimationFrame, validate_fps


@dataclass(frozen=True, slots=True, init=False)
class StatusBar:
    """Describe an immutable fixed, dynamic, responsive, or animated status line.

    Use ``static(text)``, ``dynamic(renderer)``, ``responsive(renderer)``, or
    ``animated(renderer, fps=12)``;
    direct construction is rejected. Install the result with
    ``TerminalMenu.set_status_bar()`` to reserve one bottom terminal row even
    while the menu box is hidden. The status configuration has no public mutable
    fields; replace or clear it through the menu's methods.

    Providers run synchronously on the UI thread during rendering, not when a
    factory or ``set_status_bar()`` is called. They must be fast and non-blocking
    and return a string. A non-string result raises ``TypeError`` at rendering
    time; provider exceptions propagate through the application loop.
    Dynamic providers are evaluated on every UI render. The active menu schedules
    periodic status frames at a nominal 60 Hz; immediate UI or explicit render
    requests can cause additional evaluations. Responsive providers cache output
    until installation, terminal width change, or ``menu.refresh_status_bar()``
    requests reevaluation.
    Animated providers receive a width and an ``AnimationFrame`` on the menu's
    active-time timeline at their configured maximum rate. Covered menus pause
    that timeline; sources added later join its current phase.

    Rendering removes newline characters instead of creating additional rows,
    expands tabs to eight-cell stops measured from column zero, and clips the
    resulting line to terminal width without wrapping. Safe SGR colors/styles
    and HTTP(S) OSC 8 hyperlinks are retained; other terminal controls are removed.
    """

    _kind: Literal["static", "dynamic", "responsive", "animated"]
    _producer: Callable[[int], str]
    _animated_renderer: Callable[[int, AnimationFrame], str] | None
    fps: float | None

    def __init__(self) -> None:
        """Reject direct construction in favor of an explicit status factory.

        Use ``StatusBar.static(text)``, ``StatusBar.dynamic(renderer)``, or
        ``StatusBar.responsive(renderer)`` and install the returned configuration
        with ``TerminalMenu.set_status_bar()``.

        Raises:
            TypeError: Always; direct construction is unsupported.
        """
        raise TypeError("Use a named StatusBar factory")

    @classmethod
    def _create(
        cls,
        kind: Literal["static", "dynamic", "responsive", "animated"],
        producer: Callable[[int], str],
    ) -> StatusBar:
        status = object.__new__(cls)
        object.__setattr__(status, "_kind", kind)
        object.__setattr__(status, "_producer", producer)
        object.__setattr__(status, "_animated_renderer", None)
        object.__setattr__(status, "fps", None)
        return status

    @classmethod
    def animated(
        cls,
        renderer: Callable[[int, AnimationFrame], str],
        *,
        fps: float = 12,
    ) -> StatusBar:
        """Create a width-aware status line sampled on the menu timeline.

        The renderer runs on the UI thread when its frame is due. It must be
        fast, return a string, and should derive its output from ``frame``.
        """
        if not callable(renderer):
            raise TypeError("StatusBar.animated() requires a callable")
        rate = validate_fps(fps)
        status = cls._create(
            "animated", lambda width: renderer(width, AnimationFrame(0.0, 0))
        )
        object.__setattr__(status, "_animated_renderer", renderer)
        object.__setattr__(status, "fps", rate)
        return status

    @classmethod
    def static(cls, text: str) -> StatusBar:
        """Create an immutable status description from fixed text.

        Install the result with ``TerminalMenu.set_status_bar()``. Rendering
        removes newlines, expands tabs to eight-cell stops from column zero, and
        clips the line to terminal width without wrapping. Safe SGR colors/styles
        and HTTP(S) OSC 8 hyperlinks remain; other terminal controls are removed.
        Even an empty string reserves one bottom row until the status is cleared.

        Args:
            text: Fixed Unicode status text. Must be a string.

        Returns:
            A ``StatusBar`` configuration containing the supplied text.

        Raises:
            TypeError: If ``text`` is not a string.
        """
        if not isinstance(text, str):
            raise TypeError("StatusBar.static() requires a str")
        return cls._create("static", lambda width: text)

    @classmethod
    def dynamic(cls, renderer: Callable[[], str]) -> StatusBar:
        """Create dynamic status with nominal 60 Hz periodic UI scheduling.

        The factory only stores the provider. After installation with
        ``TerminalMenu.set_status_bar()``, the active menu calls it synchronously
        on the UI thread during every render, including while the menu box is
        hidden. Periodic status frames are scheduled at a nominal 60 Hz;
        immediate UI or explicit render requests can cause additional provider
        evaluations. A menu covered by a child does not schedule dynamic status
        frames. Keep the provider fast and non-blocking. Exceptions propagate through
        the application loop; a non-string return raises ``TypeError`` when drawn.

        Args:
            renderer: Callable ``renderer() -> str`` reading current application
                state. It receives no arguments and is not invoked by this call.
                Rendering removes newlines, expands tabs to eight-cell stops
                from column zero, and clips to terminal width without wrapping.
                Safe SGR colors/styles and HTTP(S) OSC 8 hyperlinks are retained;
                other terminal controls are removed.

        Returns:
            An immutable dynamic ``StatusBar`` configuration to install on a menu.

        Raises:
            TypeError: If ``renderer`` is not callable.
        """
        if not callable(renderer):
            raise TypeError("StatusBar.dynamic() requires a callable")
        return cls._create("dynamic", lambda width: renderer())

    @classmethod
    def responsive(cls, renderer: Callable[[int], str]) -> StatusBar:
        """Create a width-aware status provider with cached output.

        After installation with ``TerminalMenu.set_status_bar()``, the provider
        runs on the UI thread at the next render and again when terminal width
        changes or ``menu.refresh_status_bar()`` requests it. Reinstalling the
        same configuration also invalidates the cache; height changes alone do
        not. The factory does not call the provider. Keep it fast and non-blocking;
        exceptions propagate during rendering, and a non-string return raises
        ``TypeError`` at that time.

        Args:
            renderer: Callable ``renderer(width: int) -> str`` receiving the
                nonnegative full terminal width in cells, not the menu's inner
                width. It is not invoked by this call. Rendering removes
                newlines, expands tabs to eight-cell stops from column zero,
                and clips to that width without wrapping. Safe SGR colors/styles
                and HTTP(S) OSC 8 hyperlinks are retained; other terminal
                controls are removed.

        Returns:
            An immutable responsive ``StatusBar`` configuration to install on a menu.

        Raises:
            TypeError: If ``renderer`` is not callable.
        """
        if not callable(renderer):
            raise TypeError("StatusBar.responsive() requires a callable")
        return cls._create("responsive", renderer)
