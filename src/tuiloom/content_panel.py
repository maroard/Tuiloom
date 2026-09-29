from __future__ import annotations

from enum import Enum
from math import isfinite
from typing import TYPE_CHECKING

from tuiloom.configuration import AutoScrollMode
from tuiloom.panel_runtime import PanelRuntime
from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.screen_content import ScreenContent

if TYPE_CHECKING:
    from tuiloom.terminal_menu import TerminalMenu


class _Unchanged(Enum):
    VALUE = "unchanged"


class ContentPanel:
    """Expose one menu-owned text panel through a stable mutation handle.

    Obtain registered handles from ``TerminalMenu.add_content_panel()``. Direct
    construction stores configuration but does not register the panel, claim a
    stream, or start source work; its mutations and ``position`` lookup fail
    until it belongs to the menu. During application operation, call mutation
    methods on the UI thread. They validate ownership before applying changes.
    Removal immediately invalidates mutations and ``position``, while other
    read-only properties continue to expose the last configured values.

    Replacing content preserves this handle, its description, auto-scroll policy,
    position, and layout settings. A live old worker is cancelled cooperatively;
    the newest replacement is mounted only after that worker stops. Collapsing
    changes physical height without suspending or discarding source work.

    Attributes:
        description: Read-only label shown on panel borders when multiple panels
            or a shutdown view are displayed, and used to identify pending work.
        position: Read-only zero-based index in the owning menu's current panel
            order. Lookup raises ``ValueError`` after removal or if unregistered.
        auto_scroll: Read-only stream-following policy: ``None`` for manual
            scrolling, ``"smart"`` to follow while at the bottom, or ``"strict"``
            to follow every future chunk batch.
        content: Read-only mounted ``ScreenContent`` configuration. It remains
            the old configuration while a replacement waits for its worker.
        weight: Read-only finite positive share of expanded panel height. Shares
            include each panel's two border rows.
        min_height: Read-only positive expanded content-row minimum, excluding
            borders. Insufficient terminal space produces the terminal-too-small
            view instead of lowering this bound.
        max_height: Read-only expanded content-row maximum, excluding borders.
            ``None`` imposes no configured upper bound.
        collapsed: Read-only flag selecting fixed collapsed sizing. Initially
            ``False``; collapse does not stop the content producer.
        collapsed_height: Read-only positive content-row count used while
            collapsed, excluding borders and independent of the expanded height
            bounds.
    """

    __slots__ = (
        "__weakref__",
        "_menu",
        "_content",
        "_description",
        "_auto_scroll",
        "_weight",
        "_min_height",
        "_max_height",
        "_collapsed",
        "_collapsed_height",
        "_removed",
        "_runtime",
    )

    def __init__(
        self,
        menu: TerminalMenu,
        content: ScreenContent,
        description: str,
        auto_scroll: AutoScrollMode | None,
        *,
        weight: float = 1,
        min_height: int = 1,
        max_height: int | None = None,
        collapsed_height: int = 1,
    ) -> None:
        """Initialize an unregistered, expanded panel without starting a worker.

        Normally use ``TerminalMenu.add_content_panel()`` to construct and
        register a panel together. This constructor stores the menu and settings
        and prepares text rendering, but does not insert the handle into the
        menu or enforce single-stream ownership. Consequently, direct handles
        cannot be mutated through the public methods or queried for ``position``.
        The menu, description, and auto-scroll mode are stored without validation.

        Args:
            menu: Required owning menu to which public mutations are delegated.
                There is no default; this constructor does not register itself.
            content: Required ``ScreenContent`` source configuration. Static
                content is normalized immediately; other producers are not
                called or consumed. There is no default.
            description: Required panel-border and shutdown label. There is no
                default or runtime type validation here.
            auto_scroll: Required stream-following mode: ``None`` for manual,
                ``"smart"`` to follow while at the bottom, or ``"strict"`` to
                follow each future chunk batch. There is no default or runtime
                validation here; other source kinds do not use this policy.
            weight: Finite positive relative share of expanded physical height,
                including two border rows per panel. Defaults to 1. Integers and
                floats are accepted, excluding booleans.
            min_height: Positive integer minimum expanded content rows, excluding
                borders. Defaults to 1; booleans are rejected. If panel minimums
                cannot fit, a terminal-too-small view replaces the normal layout.
            max_height: Positive integer maximum expanded content rows, excluding
                borders, and at least ``min_height``. Defaults to ``None`` for no
                configured upper bound; booleans are rejected.
            collapsed_height: Positive integer content rows used after collapse,
                excluding borders and independent of expanded bounds. Defaults
                to 1; booleans are rejected. The panel starts expanded.

        Raises:
            TypeError: If ``content`` is not ``ScreenContent``, ``weight`` is not
                an integer or float excluding booleans, or a height has an
                invalid type. Only ``max_height`` accepts ``None``.
            ValueError: If ``weight`` is nonpositive or nonfinite, a height is
                nonpositive, or ``max_height`` is less than ``min_height``.
        """
        self._menu = menu
        if not isinstance(content, ScreenContent):
            raise TypeError("ContentPanel content must be a ScreenContent")
        self._validate_layout(weight, min_height, max_height)
        self._validate_collapsed_height(collapsed_height)
        self._content = content
        self._description = description
        self._auto_scroll = auto_scroll
        self._weight = weight
        self._min_height = min_height
        self._max_height = max_height
        self._collapsed = False
        self._collapsed_height = collapsed_height
        self._removed = False
        self._runtime = PanelRuntime(
            ContentRenderer(content),
            responsive_refresh_pending=content._kind in ("responsive", "animated"),
        )

    @property
    def description(self) -> str:
        """Read the configured panel-border and shutdown-work label.

        Border labels appear when multiple panels or a shutdown view are shown.
        This property remains readable after removal; use ``set_description()``
        to change a registered panel's label.

        Returns:
            The last configured description string.
        """
        return self._description

    @property
    def position(self) -> int:
        """Look up the panel's current position in its owning menu.

        Positions change as panels are inserted, moved, or removed. Unlike the
        other configuration properties, this lookup requires a registered handle.

        Returns:
            The zero-based index among the owning menu's content panels.

        Raises:
            ValueError: If the panel has been removed or is not registered in its
                owning menu, including a directly constructed handle.
        """
        return self._menu._position_of_content_panel(self)

    @property
    def auto_scroll(self) -> AutoScrollMode | None:
        """Read the policy used when future stream chunk batches arrive.

        ``None`` leaves scrolling manual. ``"smart"`` follows new output until
        the user scrolls upward and resumes on returning to the bottom.
        ``"strict"`` follows every batch even after manual upward scrolling.
        Non-stream content does not use this policy. The last configured value
        remains readable after removal.

        Returns:
            The configured mode, ``None``, ``"smart"``, or ``"strict"``.
        """
        return self._auto_scroll

    @property
    def content(self) -> ScreenContent:
        """Read the source configuration currently mounted in the panel.

        During deferred replacement this remains the old configuration until
        its worker stops and the latest requested source is installed. Reading
        does not consume or evaluate the source. The value remains available
        after removal, even while its worker is being retired.

        Returns:
            The currently mounted ``ScreenContent``, rather than a rendered
            snapshot or a pending replacement.
        """
        return self._content

    @property
    def weight(self) -> float:
        """Read the relative share used to allocate expanded panel height.

        The finite positive weight applies to physical rows including the two
        border rows, subject to expanded content-row bounds. Collapsed panels
        instead use their fixed height. The last configured value remains
        readable after removal.

        Returns:
            The configured positive numeric weight; integer inputs are retained
            without conversion to float.
        """
        return self._weight

    @property
    def min_height(self) -> int:
        """Read the minimum physical content height used while expanded.

        This count excludes the two border rows and is independent of responsive
        content's virtual ``min_height``. The terminal-too-small view is shown
        when panel minimums cannot fit. Collapse uses ``collapsed_height``
        instead. The value remains readable on removal.

        Returns:
            The configured positive integer minimum in content rows.
        """
        return self._min_height

    @property
    def max_height(self) -> int | None:
        """Read the upper physical content-height bound used while expanded.

        This bound excludes borders and is at least ``min_height`` when set.
        ``None`` leaves height limited by available terminal space and other
        panels. Collapse uses ``collapsed_height``
        instead. The last configured value remains readable after removal.

        Returns:
            The positive integer content-row limit, or ``None`` for no configured
            upper bound.
        """
        return self._max_height

    @property
    def collapsed(self) -> bool:
        """Read whether the panel uses fixed collapsed physical sizing.

        A collapsed panel keeps its source and worker mounted and displays
        ``collapsed_height`` content rows rather than its weighted expanded
        allocation. Panels start expanded. The value remains readable on removal.

        Returns:
            ``True`` when collapsed, otherwise ``False``.
        """
        return self._collapsed

    @property
    def collapsed_height(self) -> int:
        """Read the fixed physical content height selected by collapse.

        The positive row count excludes two border rows and does not change
        ``weight``, ``min_height``, or ``max_height``. The last configured value
        remains readable after removal.

        Returns:
            The configured positive integer collapsed content-row count.
        """
        return self._collapsed_height

    def collapse(self) -> None:
        """Display fixed collapsed height while keeping the source running.

        The panel uses ``collapsed_height`` content rows plus its two borders;
        its expanded weight and height bounds remain configured for ``expand()``.
        Source state and scroll offsets are retained within the new viewport
        bounds, and responsive content follows its normal policy if the effective
        virtual size changes. Calling this on an already collapsed panel has no
        effect. Use the UI thread while the application is running.

        Raises:
            ValueError: If the panel has been removed or is not registered in its
                owning menu.
        """
        self._menu._set_content_panel_collapsed(self, True)

    def expand(self) -> None:
        """Resume weighted sizing with the configured expanded height bounds.

        Source state and scroll offsets are retained within the new viewport
        bounds. Responsive content follows its normal policy if the effective
        virtual size changes. Calling this on an already expanded panel has no
        effect. Use the UI thread while the application is running.

        Raises:
            ValueError: If the panel has been removed or is not registered in its
                owning menu.
        """
        self._menu._set_content_panel_collapsed(self, False)

    def toggle_collapse(self) -> None:
        """Switch between fixed collapsed height and weighted expanded sizing.

        Collapsed sizing uses ``collapsed_height`` content rows plus two border
        rows; expanded sizing uses the configured weight and height bounds.
        Source work and scroll state stay mounted within the new viewport bounds,
        and responsive content follows its normal policy if the effective virtual
        size changes. Use the UI thread while the application is running.

        Raises:
            ValueError: If the panel has been removed or is not registered in its
                owning menu.
        """
        self._menu._set_content_panel_collapsed(self, not self._collapsed)

    def set_collapsed_height(self, height: int) -> None:
        """Set the fixed content height used while the panel is collapsed.

        The new value also applies when a currently expanded panel is collapsed
        later. Expanded weight and height bounds are preserved; changing this
        setting does not collapse the panel. Validation finishes before any
        setting changes. Use the UI thread while the application is running.

        Args:
            height: Required positive integer number of content rows, excluding
                the two border rows. There is no default; booleans are rejected.

        Raises:
            TypeError: If ``height`` is not an integer or is a boolean.
            ValueError: If ``height`` is zero or negative, or the panel has been
                removed or is not registered in its owning menu.
        """
        self._menu._set_content_panel_collapsed_height(self, height)

    @staticmethod
    def _validate_collapsed_height(height: int) -> None:
        if isinstance(height, bool) or not isinstance(height, int):
            raise TypeError("collapsed_height must be a positive integer")
        if height <= 0:
            raise ValueError("collapsed_height must be a positive integer")

    def set_layout(
        self,
        *,
        weight: float = 1,
        min_height: int = 1,
        max_height: int | None = None,
    ) -> None:
        """Replace all expanded sizing options, resetting omitted values.

        Unlike ``update_layout()``, calling ``set_layout(weight=2)`` also resets
        ``min_height`` to 1 and ``max_height`` to ``None``. Validation is atomic:
        invalid input leaves every layout value unchanged. Collapsed state and
        ``collapsed_height`` are preserved; these expanded settings apply when
        the panel is expanded again. Bounds describe the physical viewport,
        independently of responsive content's virtual size minimums. If minimum
        frames cannot fit, the terminal-too-small view is displayed. Use the UI
        thread while the application is running.

        Args:
            weight: Finite positive relative share of expanded physical height,
                including two border rows per panel. Defaults to 1. Integers and
                floats are accepted, excluding booleans.
            min_height: Positive integer expanded content-row minimum, excluding
                borders. Defaults to 1; booleans are rejected.
            max_height: Positive integer expanded content-row maximum, excluding
                borders, and at least ``min_height``. Defaults to ``None`` for no
                configured upper bound; booleans are rejected.

        Raises:
            TypeError: If ``weight`` is not an integer or float excluding booleans,
                or a height has an invalid type. Only ``max_height`` accepts
                ``None``.
            ValueError: If ``weight`` is nonpositive or nonfinite, a height is
                nonpositive, ``max_height`` is below ``min_height``, or the panel
                has been removed or is not registered in its owning menu.
        """
        self._menu._set_content_panel_layout(self, weight, min_height, max_height)

    def update_layout(
        self,
        *,
        weight: float | _Unchanged = _Unchanged.VALUE,
        min_height: int | _Unchanged = _Unchanged.VALUE,
        max_height: int | None | _Unchanged = _Unchanged.VALUE,
    ) -> None:
        """Change only supplied expanded sizing options as one validated update.

        Omitted arguments retain their current values; unlike ``set_layout()``,
        ``update_layout(weight=2)`` preserves both height bounds. Explicit
        ``max_height=None`` removes the upper bound. Validation uses the complete
        resulting layout, and failure leaves all settings unchanged. Collapsed
        state and its fixed height are preserved. Bounds describe physical
        content rows independently of responsive virtual size minimums; frames
        that cannot meet the minimums show the terminal-too-small view. Use the
        UI thread while the application is running.

        Args:
            weight: New finite positive relative share of expanded physical
                height, including two border rows per panel. Omission retains
                the current weight. Integers and floats are accepted, excluding
                booleans.
            min_height: New positive integer minimum expanded content rows,
                excluding borders. Omission retains the current minimum;
                booleans and ``None`` are rejected.
            max_height: New positive integer maximum expanded content rows,
                excluding borders, and at least the resulting ``min_height``.
                Omission retains the current bound; explicit ``None`` removes
                it. Booleans are rejected.

        Raises:
            TypeError: If a supplied weight is not an integer or float excluding
                booleans, or a supplied height has an invalid type. Only
                ``max_height`` accepts ``None``.
            ValueError: If the resulting weight is nonpositive or nonfinite, a
                height is nonpositive, ``max_height`` is below ``min_height``, or
                the panel has been removed or is not registered in its menu.
        """
        self._menu._set_content_panel_layout(
            self,
            self._weight if isinstance(weight, _Unchanged) else weight,
            self._min_height if isinstance(min_height, _Unchanged) else min_height,
            self._max_height if isinstance(max_height, _Unchanged) else max_height,
        )

    @staticmethod
    def _validate_layout(
        weight: float, min_height: int, max_height: int | None
    ) -> None:
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise TypeError("weight must be a finite positive number")
        if weight <= 0 or (isinstance(weight, float) and not isfinite(weight)):
            raise ValueError("weight must be a finite positive number")
        if min_height is None:
            raise TypeError("min_height must be a positive integer")
        ScreenContent._validate_minimum("min_height", min_height)
        ScreenContent._validate_minimum("max_height", max_height)
        if max_height is not None and max_height < min_height:
            raise ValueError("max_height must be greater than or equal to min_height")

    def set_content(self, content: ScreenContent) -> None:
        """Request a replacement source while preserving panel identity and layout.

        Description, position, auto-scroll policy, collapsed state, and height
        settings are retained. When the old worker is alive, request cooperative
        cancellation and return without waiting for it; the new source mounts
        on a later application loop turn after that worker stops. Repeated
        requests keep only the latest replacement. ``content`` reports the old
        configuration until mounting, and events from the old source are ignored.
        Without a live worker, mounting is immediate. Mounting clears old text
        history and scroll offsets and resets smart following.

        A replacement stream is claimed immediately for this panel. Its worker
        starts after retirement, and the old stream remains claimed until its
        worker stops. Other panels in the same application cannot use either
        claimed stream. An optional old-source ``cancel()`` hook runs on the
        caller's thread and must return promptly and unblock the source call;
        hook errors propagate to the caller. Use the UI thread while running.

        Args:
            content: Required new ``ScreenContent`` configuration, with no
                default. To consume a stream independently, provide a fresh
                iterator rather than one claimed by another panel.

        Raises:
            TypeError: If ``content`` is not a ``ScreenContent`` instance.
            ValueError: If the panel is removed or unregistered in its owning
                menu, or another panel in the same application owns the stream.
        """
        self._menu._set_content_panel_content(self, content)

    def refresh(self) -> None:
        """Request another responsive or animated snapshot at the current size.

        This works with both ``"resize"`` and ``"continuous"`` refresh modes,
        including when the size has not changed. It does not evaluate the
        producer synchronously: requests coalesce, a worker computes the latest
        one outside the UI thread, and its result applies on a later loop turn.
        Without known layout or a running worker, work remains pending until
        layout and a worker are available. Waiting to quit defers new work.
        Producer failures propagate later from the application loop. Validation
        refers to the mounted ``content``, even during a pending replacement.
        Use the UI thread while the application is running.

        Raises:
            RuntimeError: If mounted content is fixed text, fixed lines, a
                dynamic producer, or a stream rather than responsive or
                animated content.
            ValueError: If the panel has been removed or is not registered in its
                owning menu.
        """
        self._menu._refresh_content_panel(self)

    def set_description(self, description: str) -> None:
        """Replace the label used on panel borders and for shutdown work.

        Borders show labels when multiple panels or a shutdown view are present.
        The current worker's description is updated too. This change preserves
        content and layout and performs no runtime string validation. Use the UI
        thread while the application is running.

        Args:
            description: Required replacement label string. There is no default;
                an empty string suppresses the panel-border label.

        Raises:
            ValueError: If the panel has been removed or is not registered in its
                owning menu.
        """
        self._menu._set_content_panel_description(self, description)

    def set_auto_scroll(self, mode: AutoScrollMode | None) -> None:
        """Choose how future stream chunk batches affect vertical scrolling.

        ``None`` leaves scrolling manual. ``"smart"`` follows new output until
        the user scrolls upward, then resumes on returning to the bottom.
        ``"strict"`` moves to the bottom for every future batch even after
        upward scrolling. Changing the policy resets smart following and pending
        auto-scroll state without replacing content or immediately moving the
        viewport. Other source kinds retain the setting but do not apply it.
        Use the UI thread while the application is running.

        Args:
            mode: Required new policy, ``None``, ``"smart"``, or ``"strict"``.
                There is no default; passing ``None`` disables following.

        Raises:
            ValueError: If ``mode`` is unsupported, or the panel has been removed
                or is not registered in its owning menu.
        """
        self._menu._set_content_panel_auto_scroll(self, mode)

    def move(self, position: int) -> None:
        """Move the existing panel within its owning menu's display order.

        The handle, content, worker, and layout settings are preserved. Other
        panels' numeric positions may change. Use the UI thread while the
        application is running.

        Args:
            position: Required zero-based destination among existing panels,
                between 0 and the panel count minus 1. There is no default;
                booleans are rejected. Although annotated as ``int``, the
                runtime also accepts ``None`` to move the panel to the end.

        Raises:
            TypeError: If ``position`` is a boolean or a noninteger other than
                ``None``.
            ValueError: If the integer position is outside the existing panel
                range, or this panel is removed or unregistered in its menu.
        """
        self._menu._move_content_panel(self, position)

    def remove(self) -> None:
        """Remove the panel immediately and cooperatively retire its source.

        The handle leaves the menu's display order and becomes invalid for all
        mutations and ``position`` lookup; other properties retain their last
        values. A live worker receives cancellation and is tracked until it
        stops, without blocking this method. Any queued replacement is discarded.
        The old stream remains claimed by this panel until retirement finishes,
        so another panel cannot consume it concurrently. An optional source
        ``cancel()`` hook runs on the caller's thread, must return promptly and
        unblock the source, and propagates its errors to the caller. Normal
        application shutdown still waits for a blocked retired worker. Use the
        UI thread while the application is running.

        Raises:
            ValueError: If the panel has already been removed or is not registered
                in its owning menu. Removal is not idempotent.
        """
        self._menu._remove_content_panel(self)
