"""Explicit descriptions of content rendered in a terminal panel."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal, cast

from tuiloom.animation import AnimationFrame, validate_fps
from tuiloom.configuration import ContentRefreshMode

type ContentValue = str | list[str]
type ContentKind = Literal[
    "static", "lines", "stream", "dynamic", "responsive", "animated"
]
type ContentProducer = (
    str
    | tuple[str, ...]
    | Iterator[str]
    | Callable[[], ContentValue]
    | Callable[[ContentSize], ContentValue]
    | Callable[[ContentSize, AnimationFrame], ContentValue]
)


@dataclass(frozen=True, slots=True)
class ContentSize:
    """Store the immutable virtual size supplied to a responsive text producer.

    Both dimensions exclude panel borders. Responsive content minimums can make
    this size larger than the physical viewport, so excess output can be
    scrolled. Both fields are required when constructing a size manually, with
    no defaults or runtime type/range validation. Zero represents no available
    cells or rows and does not imply a one-cell minimum.
    The terminal renderer skips panel layout when the terminal cannot fit its
    frames, rather than sending a new zero-size request.

    Attributes:
        width: Read-only ``int`` virtual width in terminal display cells, excluding
            borders. A wide Unicode grapheme can occupy more than one cell.
        height: Read-only ``int`` virtual height in content rows, excluding borders.
    """

    width: int
    height: int


@dataclass(frozen=True, slots=True, init=False)
class ScreenContent:
    """Describe an immutable fixed, streaming, or generated panel text source.

    Use ``static`` for a string, ``lines`` for fixed rows, ``stream`` for an
    iterator of text chunks, ``dynamic`` for repeated complete snapshots, or
    ``responsive`` for snapshots depending on virtual panel dimensions, or
    ``animated`` for size-aware snapshots tied to the menu timeline. Direct
    construction is rejected. Factories configure a source without consuming
    its iterator or calling its producer; source work begins when its owning
    menu is initialized. A stream is consumed by only one panel per application,
    including while its previous worker is being retired.

    Nonfixed sources run on non-daemon workers outside the UI thread; synchronize
    state shared with UI callbacks. Dynamic producers run at most sixty times
    per second. Continuous responsive mode schedules periodic requests at a
    nominal sixty-hertz cadence; layout changes and explicit refreshes can add
    requests. Resize-responsive mode requests work for layout changes and
    explicit refreshes. Responsive calls remain serialized and pending requests
    coalesce to the newest size. Animated calls also remain serialized and
    coalesce to the newest size and frame at their configured maximum rate.
    Producer failures are reraised from the
    application loop. Cancellation is cooperative: a running source
    call must finish before its replacement or normal shutdown can finish.

    Text supports Unicode display cells, SGR color/style sequences, and safe
    HTTP(S) terminal hyperlinks. Tabs expand to eight-cell stops and other
    terminal controls are removed, except stream carriage returns used to
    replace the unfinished row. Content wider or taller than the viewport is
    scrollable rather than automatically wrapped.

    Attributes:
        min_width: Read-only responsive or animated virtual width minimum in
            terminal display
            cells, excluding borders. ``None`` uses the physical viewport width;
            always ``None`` for other source kinds.
        min_height: Read-only responsive or animated virtual height minimum in
            content rows,
            excluding borders. ``None`` uses the physical viewport height;
            always ``None`` for other source kinds. Independent of a panel's
            visible height bounds.
        refresh_mode: Read-only responsive evaluation policy: ``"resize"`` for
            first layout, layout changes, and explicit panel refreshes, or
            ``"continuous"`` for additional periodic updates. ``None`` for other
            source kinds.
        fps: Read-only maximum animation rate in frames per second for animated
            content, or ``None`` for other source kinds.
    """

    _kind: ContentKind
    _producer: ContentProducer
    min_width: int | None
    min_height: int | None
    refresh_mode: ContentRefreshMode | None
    fps: float | None

    def __init__(self) -> None:
        """Reject direct construction; select a named source factory instead.

        Raises:
            TypeError: Always, because a source kind and producer must be chosen
                through a named ``ScreenContent`` factory.
        """
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
        fps: float | None = None,
    ) -> ScreenContent:
        content = object.__new__(cls)
        object.__setattr__(content, "_kind", kind)
        object.__setattr__(content, "_producer", producer)
        object.__setattr__(content, "min_width", min_width)
        object.__setattr__(content, "min_height", min_height)
        object.__setattr__(content, "refresh_mode", refresh_mode)
        object.__setattr__(content, "fps", fps)
        return content

    @classmethod
    def animated(
        cls,
        renderer: Callable[[ContentSize, AnimationFrame], ContentValue],
        *,
        fps: float = 12,
        min_width: int | None = None,
        min_height: int | None = None,
    ) -> ScreenContent:
        """Render complete panel snapshots on due frames of the menu timeline.

        Calls run serially on the panel worker. The newest pending size/frame
        supersedes older requests, and stale results are discarded.
        """
        if not callable(renderer):
            raise TypeError("ScreenContent.animated() requires a callable")
        cls._validate_minimum("min_width", min_width)
        cls._validate_minimum("min_height", min_height)
        return cls._create(
            "animated",
            renderer,
            min_width=min_width,
            min_height=min_height,
            fps=validate_fps(fps),
        )

    @classmethod
    def static(cls, text: str) -> ScreenContent:
        """Create fixed panel text that is normalized when mounted.

        Text is split into rows, with an empty string displayed as one blank row
        and no additional blank row for a final newline. Tabs expand to
        eight-cell stops. SGR styles and safe HTTP(S) terminal hyperlinks are
        retained and continued across rows; other terminal controls are removed.
        Long rows are horizontally scrollable rather than wrapped. This source
        needs no worker and is marked complete immediately.

        Args:
            text: Required fixed text, including any newline-separated rows and
                supported terminal formatting. There is no default.

        Returns:
            An immutable content configuration holding the supplied string.

        Raises:
            TypeError: If ``text`` is not a string.
        """
        if not isinstance(text, str):
            raise TypeError("ScreenContent.static() requires a str")
        return cls._create("static", text)

    @classmethod
    def lines(cls, lines: list[str]) -> ScreenContent:
        """Create fixed panel rows from an immutable copy of a string list.

        Each list entry is one row; embedded newlines and other unsupported
        terminal controls are removed rather than creating more rows. An empty
        list displays one blank row. Tabs expand to eight-cell stops, while SGR
        styles and safe HTTP(S) terminal hyperlinks are retained and closed at
        each row's end. Formatting does not continue from one entry to the next.
        Long rows are horizontally scrollable rather than wrapped. This source
        needs no worker and is marked complete immediately.

        Args:
            lines: Required list of fixed row strings. Later mutations of the
                list do not affect the configuration. There is no default.

        Returns:
            An immutable content configuration containing a tuple copy of the
            supplied rows.

        Raises:
            TypeError: If ``lines`` is not a list or any entry is not a string.
        """
        if not isinstance(lines, list) or not all(
            isinstance(line, str) for line in lines
        ):
            raise TypeError("ScreenContent.lines() requires a list[str]")
        return cls._create("lines", tuple(lines))

    @classmethod
    def stream(cls, iterator: Iterator[str]) -> ScreenContent:
        """Configure an iterator consumed as successive terminal text chunks.

        One non-daemon worker calls ``next(iterator)`` serially outside the UI
        thread, consuming as output queue capacity allows rather than at a fixed
        frame rate. Chunks concatenate into rows: newlines commit a row, CRLF
        commits one row, and a bare carriage return replaces the unfinished row.
        ANSI sequences and Unicode graphemes can cross chunk boundaries. Tabs
        expand to eight-cell stops; SGR styles and safe HTTP(S) hyperlinks are
        retained, and other terminal controls are removed. Completed rows remain
        in scrollable history without a default limit. Completion retains the
        unfinished row without inventing a final blank row.

        The factory does not consume the iterator. An iterator can be mounted by
        only one panel in the same application, including queued replacement
        and retirement; create a fresh iterator for independent consumers.
        Producer exceptions and non-string chunks propagate from the application
        loop, with non-string chunks producing ``TypeError``.

        Replacement, removal, or shutdown calls an optional ``cancel()`` hook on
        the caller's thread, which is the UI thread during normal operation. It
        must return promptly and unblock any ``next()`` call; its errors propagate
        to the caller. An optional ``close()`` hook runs on the worker after
        completion or cancellation. Close-hook failures reach the application
        loop after normal consumption, but cancellation suppresses worker events.
        Normal shutdown waits for the worker to stop: Python cannot interrupt a
        blocked source call by cancelling its thread.

        Args:
            iterator: Required synchronous iterator yielding string chunks, not
                merely an iterable such as a list. There is no default.

        Returns:
            An immutable configuration referring to the same iterator, without
            copying, consuming, or starting it.

        Raises:
            TypeError: If ``iterator`` is not an iterator. Chunk type errors
                occur later when the application consumes the source.
        """
        if not isinstance(iterator, Iterator):
            raise TypeError("ScreenContent.stream() requires an Iterator[str]")
        return cls._create("stream", iterator)

    @classmethod
    def dynamic(cls, renderer: Callable[[], ContentValue]) -> ScreenContent:
        """Configure a producer of repeatedly replaced complete text snapshots.

        A non-daemon worker calls ``renderer()`` outside the UI thread at most
        sixty times per second, starting on the first application loop turn.
        Evaluations never overlap within one panel, and slow calls reduce the
        update rate. Each result replaces previous content instead of extending
        history. Return a string split into rows or a list of strings treated as
        individual rows; embedded newlines in list entries are removed. Empty
        text or an empty list displays one blank row. Tabs expand to eight-cell
        stops; SGR styles and safe HTTP(S) terminal hyperlinks are retained, and
        unsupported terminal controls are removed. Rows remain scrollable
        rather than automatically wrapped.

        The factory does not call the producer. Producer exceptions propagate
        from the application loop; invalid results, including non-string list
        entries, produce ``TypeError`` there. Synchronize mutable state shared
        with UI callbacks. Waiting to quit pauses new evaluations until waiting
        is cancelled. Replacement, removal, or shutdown calls any ``cancel()``
        hook on the caller's thread, normally the UI thread; the hook must return
        promptly and unblock a running call. Its errors propagate to the caller.
        A running call must return before replacement or normal shutdown can
        finish; no ``close()`` hook is invoked for this source kind.

        Args:
            renderer: Required synchronous callable taking no arguments and
                returning a complete string or ``list[str]`` snapshot. There is
                no default; the callable's signature is not inspected.

        Returns:
            An immutable configuration referring to the supplied producer,
            without invoking it or starting its worker.

        Raises:
            TypeError: If ``renderer`` is not callable. Result type errors occur
                later when the application evaluates the producer.
        """
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
        """Configure complete text snapshots computed for a virtual panel size.

        A non-daemon worker calls ``renderer(size)`` outside the UI thread with a
        ``ContentSize`` excluding borders. Optional minimums enlarge the virtual
        size beyond a smaller physical viewport; excess output remains
        scrollable rather than automatically wrapped. Minimums do not reserve
        physical rows or columns. The terminal renderer skips new panel layout
        when its frames do not fit, rather than requesting a zero-size result.

        Return a string split into rows or a list of strings treated as individual
        rows; embedded newlines in list entries are removed. Empty text or an
        empty list displays one blank row. Tabs expand to eight-cell stops; SGR
        styles and safe HTTP(S) hyperlinks are retained, and unsupported terminal
        controls are removed. Each snapshot replaces previous content without
        accumulating history. Calls are serialized per panel, pending requests
        coalesce to the latest size, and superseded results and failures are
        discarded. Current producer failures propagate from the application
        loop, including ``TypeError`` for results other than a string or
        ``list[str]``.

        Resize mode evaluates on first valid layout, effective virtual size
        changes, and explicit ``ContentPanel.refresh()`` requests. Continuous
        mode additionally schedules periodic evaluations at a nominal sixty-hertz
        cadence once a layout is known; layout changes and explicit refreshes can
        request additional evaluations. Slow calls reduce the update rate, and
        calls remain serialized with pending requests coalesced. Both modes defer
        new work while waiting to quit. Synchronize mutable state shared with UI
        callbacks. Replacement, removal, or shutdown calls an optional
        ``cancel()`` hook on the caller's thread, normally the UI thread; it must
        return promptly and unblock a running call. Hook failures propagate to
        the caller. The current call must return before replacement or normal
        shutdown finishes; no ``close()`` hook is invoked for this source kind.

        Args:
            renderer: Required synchronous callable receiving one ``ContentSize``
                and returning a complete string or ``list[str]`` snapshot. The
                factory does not call it or inspect its signature.
            min_width: Positive integer virtual width minimum in terminal display
                cells, excluding borders. Defaults to ``None``, using the
                physical viewport width. Boolean values are rejected.
            min_height: Positive integer virtual height minimum in content rows,
                excluding borders. Defaults to ``None``, using the physical
                viewport height. Boolean values are rejected.
            refresh_mode: ``"resize"`` (the default) for layout changes and
                explicit refreshes, or ``"continuous"`` for additional repeated
                evaluations at a known size.

        Returns:
            An immutable configuration referring to the producer and recording
            the virtual minimums and refresh mode, without starting any work.

        Raises:
            TypeError: If ``renderer`` is not callable, or a minimum is neither
                ``None`` nor an integer excluding booleans. Result type errors
                occur later during application evaluation.
            ValueError: If a minimum is zero or negative, or ``refresh_mode`` is
                neither ``"resize"`` nor ``"continuous"``.
        """
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

    def _animated(self) -> Callable[[ContentSize, AnimationFrame], ContentValue]:
        return cast(
            Callable[[ContentSize, AnimationFrame], ContentValue], self._producer
        )
