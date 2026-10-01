from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from math import isfinite
from typing import TYPE_CHECKING

from tuiloom.command import PanelCommandCallback, PanelKeyCommand
from tuiloom.configuration import AutoScrollMode, SelectionStyle
from tuiloom.key_binding import KeyBinding
from tuiloom.panel_runtime import PanelRuntime
from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.screen_content import ScreenContent
from tuiloom.selectable import SelectableItem, SelectionChangeContext

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
    the newest replacement is mounted only after that worker stops. A row owns
    physical height; a singleton panel can still collapse through its v0.7 API.

    Attributes:
        description: Read-only label shown on panel borders when multiple panels
            or a shutdown view are displayed, and used to identify pending work.
        header: Optional title centered above the scrollable content, with a
            full-width divider. Change it with ``set_header()``.
        position: Read-only zero-based index in the owning menu's flat panel
            collection. Layout movements do not change it. Lookup raises
            ``ValueError`` after removal or if unregistered.
        auto_scroll: Read-only stream-following policy: ``None`` for manual
            scrolling, ``"smart"`` to follow while at the bottom, or ``"strict"``
            to follow every future chunk batch.
        content: Read-only mounted ``ScreenContent`` configuration. It remains
            the old configuration while a replacement waits for its worker.
        height_weight: Read-only positive share of expanded row height. A row
            uses the mean of its members' values; frame heights include borders.
        width_weight: Read-only positive share of frame width within its row,
            including the panel's two border columns.
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
        padding_top, padding_bottom, padding_left, padding_right: Read-only
            nonnegative inner padding sizes. Change selected sides with
            ``update_padding()``.
        key_commands: Read-only tuple of shortcuts registered on this panel.
        selected_index: Read-only zero-based index among selectable items, or
            ``None`` when no item is selected.
        selected_item: Read-only currently selected ``SelectableItem`` or ``None``.
        selection_style: Read-only ``"marker"`` or ``"reverse"`` rendering mode;
            change it with ``set_selection_style()``.
    """

    __slots__ = (
        "__weakref__",
        "_menu",
        "_content",
        "_description",
        "_header",
        "_auto_scroll",
        "_height_weight",
        "_width_weight",
        "_min_height",
        "_max_height",
        "_collapsed",
        "_collapsed_height",
        "_padding_top",
        "_padding_bottom",
        "_padding_left",
        "_padding_right",
        "_key_commands",
        "_removed",
        "_runtime",
        "_selected_index",
        "_selection_style",
        "_selection_callback",
    )

    def __init__(
        self,
        menu: TerminalMenu,
        content: ScreenContent,
        description: str,
        auto_scroll: AutoScrollMode | None,
        *,
        height_weight: float = 1,
        width_weight: float = 1,
        min_height: int = 1,
        max_height: int | None = None,
        collapsed_height: int = 1,
        padding_top: int = 0,
        padding_bottom: int = 0,
        padding_left: int = 0,
        padding_right: int = 0,
        selection_style: SelectionStyle = "marker",
        header: str | None = None,
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
            height_weight: Finite positive relative share of expanded physical height,
                including two border rows per panel. Defaults to 1. Integers and
                floats are accepted, excluding booleans.
            width_weight: Finite positive relative share of the row's complete
                frame width, including two border columns. Defaults to 1.
            min_height: Positive integer minimum expanded content rows, excluding
                borders. Defaults to 1; booleans are rejected. If panel minimums
                cannot fit, a terminal-too-small view replaces the normal layout.
            max_height: Positive integer maximum expanded content rows, excluding
                borders, and at least ``min_height``. Defaults to ``None`` for no
                configured upper bound; booleans are rejected.
            collapsed_height: Positive integer content rows used after collapse,
                excluding borders and independent of expanded bounds. Defaults
                to 1; booleans are rejected. The panel starts expanded.
            padding_top, padding_bottom, padding_left, padding_right:
                Nonnegative integer cells reserved inside the frame. Default to
                zero; booleans are rejected.
            selection_style: ``"marker"`` (default) or ``"reverse"`` for the
                selected item row.
            header: Optional fixed title above the scrolling viewport. It uses
                two inner rows for the title and divider.

        Raises:
            TypeError: If ``content`` is not ``ScreenContent``, either sizing
                weight has an invalid type, or a height has an invalid type.
                Only ``max_height`` accepts ``None``.
            ValueError: If either sizing weight is nonpositive or nonfinite, a
                height is nonpositive, or ``max_height`` is below ``min_height``.
        """
        self._menu = menu
        if not isinstance(content, ScreenContent):
            raise TypeError("ContentPanel content must be a ScreenContent")
        self._validate_layout(height_weight, width_weight, min_height, max_height)
        self._validate_collapsed_height(collapsed_height)
        for name, value in (
            ("padding_top", padding_top),
            ("padding_bottom", padding_bottom),
            ("padding_left", padding_left),
            ("padding_right", padding_right),
        ):
            self._validate_padding(name, value)
        self._content = content
        if selection_style not in ("marker", "reverse"):
            raise ValueError("selection_style must be 'marker' or 'reverse'")
        self._selection_style = selection_style
        self._description = description
        if header is not None and not isinstance(header, str):
            raise TypeError("panel header must be a str or None")
        self._header = header
        self._auto_scroll = auto_scroll
        self._height_weight = height_weight
        self._width_weight = width_weight
        self._min_height = min_height
        self._max_height = max_height
        self._collapsed = False
        self._collapsed_height = collapsed_height
        self._padding_top = padding_top
        self._padding_bottom = padding_bottom
        self._padding_left = padding_left
        self._padding_right = padding_right
        self._key_commands: list[PanelKeyCommand] = []
        self._removed = False
        self._runtime = PanelRuntime(
            ContentRenderer(content),
            responsive_refresh_pending=content._kind in ("responsive", "animated"),
        )
        self._selected_index: int | None = None
        self._selection_callback: Callable[[SelectionChangeContext], None] | None = None
        self._restore_selection(content)

    def set_selection_callback(
        self, callback: Callable[[SelectionChangeContext], None] | None
    ) -> None:
        """Notify changes to the selected item, after the change is committed."""
        self._menu._require_content_panel(self)
        if callback is not None and not callable(callback):
            raise TypeError("selection callback must be callable or None")
        self._selection_callback = callback

    def _notify_selection_change(
        self,
        previous_item: SelectableItem | None,
        previous_index: int | None,
        binding: KeyBinding | None = None,
    ) -> None:
        callback = self._selection_callback
        item = self.selected_item
        if callback is not None and (
            previous_index != self._selected_index or previous_item is not item
        ):
            callback(
                SelectionChangeContext(
                    self._menu.app,
                    self._menu,
                    self,
                    previous_item,
                    previous_index,
                    item,
                    self._selected_index,
                    binding,
                )
            )

    @property
    def selected_index(self) -> int | None:
        """Return the selected item's index, or None when no item is selected."""
        return self._selected_index

    @property
    def selection_style(self) -> SelectionStyle:
        """Return this panel's independent item selection style."""
        return self._selection_style

    def set_selection_style(self, style: SelectionStyle) -> None:
        """Change item selection rendering without replacing content or runtime."""
        self._menu._require_content_panel(self)
        if style not in ("marker", "reverse"):
            raise ValueError("selection_style must be 'marker' or 'reverse'")
        if self._selection_style != style:
            self._selection_style = style
            self._menu._request_menu_render()

    @property
    def selected_item(self) -> SelectableItem | None:
        """Return the selected item in mounted content, if any."""
        items = self._content._selectable_items()
        index = self._selected_index
        return items[index] if index is not None and index < len(items) else None

    def select_item(self, index: int) -> None:
        """Select an enabled item by its zero-based item index without activation."""
        self._menu._require_content_panel(self)
        if type(index) is not int:
            raise TypeError("selected item index must be an int")
        items = self._content._selectable_items()
        if not 0 <= index < len(items) or not items[index].enabled:
            raise ValueError("selected item index must identify an enabled item")
        previous_item = self.selected_item
        previous_index = self._selected_index
        self._selected_index = index
        self._runtime.selection_visibility_pending = True
        self._runtime.selection_revision += 1
        self._menu._request_menu_render()
        self._notify_selection_change(previous_item, previous_index)

    def clear_selection(self) -> None:
        """Clear the current item selection without changing panel content.

        A later arrow key selects the first enabled item. Notify the selection
        callback only when a selected item was actually cleared.
        """
        self._menu._require_content_panel(self)
        if self._selected_index is None:
            return
        previous_item = self.selected_item
        previous_index = self._selected_index
        self._selected_index = None
        self._runtime.selection_revision += 1
        self._menu._request_menu_render()
        self._notify_selection_change(previous_item, previous_index)

    def _selected_row(self) -> int | None:
        if self._selected_index is None:
            return None
        item_index = 0
        for row_index, row in enumerate(self._content._selectable_rows()):
            if isinstance(row, SelectableItem):
                if item_index == self._selected_index:
                    return row_index
                item_index += 1
        return None

    def _restore_selection(self, content: ScreenContent) -> None:
        old_item = self.selected_item if hasattr(self, "_selected_index") else None
        old_index = self._selected_index
        items = content._selectable_items()
        enabled = [index for index, item in enumerate(items) if item.enabled]
        if not enabled:
            self._selected_index = None
            self._runtime.selection_visibility_pending = True
            return
        if old_item is not None and old_item.key is not None:
            matching = next(
                (index for index in enabled if items[index].key == old_item.key), None
            )
            if matching is not None:
                self._selected_index = matching
                self._runtime.selection_visibility_pending = True
                return
        if old_index is None:
            self._selected_index = enabled[0]
        else:
            self._selected_index = min(
                enabled, key=lambda index: (abs(index - old_index), index)
            )
        self._runtime.selection_visibility_pending = True

    def _move_selection(self, delta: int, binding: KeyBinding | None = None) -> None:
        previous_item = self.selected_item
        previous_index = self._selected_index
        enabled = [
            index
            for index, item in enumerate(self._content._selectable_items())
            if item.enabled
        ]
        if not enabled:
            self._selected_index = None
            return
        if self._selected_index not in enabled:
            self._selected_index = enabled[0]
        else:
            self._selected_index = enabled[
                (enabled.index(self._selected_index) + delta) % len(enabled)
            ]
        self._runtime.selection_visibility_pending = True
        self._runtime.selection_revision += 1
        self._menu._request_menu_render()
        self._notify_selection_change(previous_item, previous_index, binding)

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
    def header(self) -> str | None:
        """Return the fixed title above the panel's scrollable content."""
        return self._header

    @property
    def _header_height(self) -> int:
        return 2 if self._header is not None else 0

    def set_header(self, header: str | None) -> None:
        """Set a centered title and divider, or remove both with None."""
        self._menu._require_content_panel(self)
        if header is not None and not isinstance(header, str):
            raise TypeError("panel header must be a str or None")
        if self._header != header:
            self._header = header
            self._menu._invalidate_renderer()

    @property
    def position(self) -> int:
        """Look up the panel's index in its menu's flat registered collection.

        Positions change as panels are inserted or removed, but not when their
        visual placement changes. Unlike the other configuration properties,
        this lookup requires a registered handle.

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
    def height_weight(self) -> float:
        """Read the relative share used to allocate expanded panel height.

        The finite positive value applies to physical rows including the two
        border rows, subject to expanded content-row bounds. Collapsed panels
        instead use their fixed height. The last configured value remains
        readable after removal.

        Returns:
            The configured positive numeric value; integer inputs are retained
            without conversion to float.
        """
        return self._height_weight

    @property
    def width_weight(self) -> float:
        """Read its relative share of row width, including border columns."""
        return self._width_weight

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
        ``height_weight``, ``min_height``, or ``max_height``. The last configured value
        remains readable after removal.

        Returns:
            The configured positive integer collapsed content-row count.
        """
        return self._collapsed_height

    @property
    def padding_top(self) -> int:
        return self._padding_top

    @property
    def padding_bottom(self) -> int:
        return self._padding_bottom

    @property
    def padding_left(self) -> int:
        return self._padding_left

    @property
    def padding_right(self) -> int:
        return self._padding_right

    @property
    def key_commands(self) -> tuple[PanelKeyCommand, ...]:
        """Return registered keyboard commands in registration order."""
        return tuple(self._key_commands)

    def add_key_command(
        self,
        binding: KeyBinding,
        label: str,
        callback: PanelCommandCallback,
    ) -> PanelKeyCommand:
        """Register a shortcut active only when this panel has input focus."""
        self._menu._require_content_panel(self)
        if not isinstance(binding, KeyBinding):
            raise TypeError("binding must be a KeyBinding")
        if not callable(callback):
            raise TypeError("callback must be callable")
        shifted_horizontal = (
            binding.key in {"left", "right"}
            and binding.shift
            and not (binding.ctrl or binding.alt)
        )
        if (
            binding.key in {"tab", "escape", "up", "down", "left", "right"}
            and not shifted_horizontal
        ) or (
            self._menu.app.keymap.action_for(binding)
            in {
                "focus",
                "back",
                "up",
                "down",
                "left",
                "right",
                "scroll_up",
                "scroll_down",
                "scroll_left",
                "scroll_right",
            }
        ):
            raise ValueError("binding is reserved for a system action")
        if any(command.binding == binding for command in self._key_commands):
            raise ValueError("binding already invokes a panel command")
        command = PanelKeyCommand(self, binding, label, callback)
        self._key_commands.append(command)
        return command

    def remove_key_command(self, command: PanelKeyCommand) -> None:
        """Remove a command owned by this panel."""
        self._menu._require_content_panel(self)
        if (
            not isinstance(command, PanelKeyCommand)
            or command._panel is not self
            or command not in self._key_commands
        ):
            raise ValueError("Panel command does not belong to this panel")
        self._key_commands.remove(command)

    def update_padding(
        self,
        *,
        top: int | None = None,
        bottom: int | None = None,
        left: int | None = None,
        right: int | None = None,
    ) -> None:
        """Change supplied inner padding sides while retaining the others."""
        self._menu._require_content_panel(self)
        for name, value in (
            ("top", top),
            ("bottom", bottom),
            ("left", left),
            ("right", right),
        ):
            if value is not None:
                self._validate_padding(name, value)
        if top is not None:
            self._padding_top = top
        if bottom is not None:
            self._padding_bottom = bottom
        if left is not None:
            self._padding_left = left
        if right is not None:
            self._padding_right = right
        self._menu._invalidate_renderer()
        if self._menu._event_loop is not None:
            self._menu._event_loop.request_render(immediate=True)

    @staticmethod
    def _validate_padding(name: str, value: int) -> None:
        if type(value) is not int:
            raise TypeError(f"{name} must be a nonnegative integer")
        if value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")

    def collapse(self) -> None:
        """Display fixed height for a singleton row, keeping the source running.

        The panel uses ``collapsed_height`` content rows plus its two borders;
        its expanded height sizing remains configured for ``expand()``.
        Source state and scroll offsets are retained within the new viewport
        bounds, and responsive content follows its normal policy if the effective
        virtual size changes. Calling this on an already collapsed panel has no
        effect. Use the UI thread while the application is running.

        Raises:
            ValueError: If the panel is unregistered or belongs to a multi-panel
                row. Use ``menu.content_layout[index].collapse()`` for that row.
        """
        self._menu._set_content_panel_collapsed(self, True)

    def expand(self) -> None:
        """Resume weighted sizing for a singleton row.

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
        """Switch a singleton row between fixed and weighted sizing.

        Collapsed sizing uses ``collapsed_height`` content rows plus two border
        rows; expanded sizing uses the configured height weight and bounds.
        Source work and scroll state stay mounted within the new viewport bounds,
        and responsive content follows its normal policy if the effective virtual
        size changes. Use the UI thread while the application is running.

        Raises:
            ValueError: If the panel has been removed or is not registered in its
                owning menu.
        """
        self._menu._set_content_panel_collapsed(self, not self._collapsed)

    def set_collapsed_height(self, height: int) -> None:
        """Set fixed collapsed content height for a singleton row.

        The new value also applies when a currently expanded panel is collapsed
        later. Expanded height sizing is preserved; changing this
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
        height_weight: float = 1,
        width_weight: float = 1,
        min_height: int = 1,
        max_height: int | None = None,
    ) -> None:
        """Replace all expanded sizing options, resetting omitted values.

        Unlike ``update_layout()``, calling ``set_layout(height_weight=2)`` also
        resets ``width_weight`` to 1, ``min_height`` to 1, and ``max_height`` to
        ``None``. Validation is atomic:
        invalid input leaves every layout value unchanged. Collapsed state and
        ``collapsed_height`` are preserved; height settings apply when the row
        expands, while width changes apply in either state. Bounds describe the
        physical viewport,
        independently of responsive content's virtual size minimums. If minimum
        frames cannot fit, the terminal-too-small view is displayed. Use the UI
        thread while the application is running.

        Args:
            height_weight: Finite positive relative share of expanded physical height,
                including two border rows per panel. Defaults to 1. Integers and
                floats are accepted, excluding booleans.
            width_weight: Finite positive share of complete frame width within
                the panel's row, including borders. Defaults to 1.
            min_height: Positive integer expanded content-row minimum, excluding
                borders. Defaults to 1; booleans are rejected.
            max_height: Positive integer expanded content-row maximum, excluding
                borders, and at least ``min_height``. Defaults to ``None`` for no
                configured upper bound; booleans are rejected.

        Raises:
            TypeError: If either weight or a height has an invalid type. Only
                ``max_height`` accepts ``None``.
            ValueError: If either weight is nonpositive or nonfinite, a height is
                nonpositive, ``max_height`` is below ``min_height``, or the panel
                has been removed or is not registered in its owning menu.
        """
        self._menu._set_content_panel_layout(
            self, height_weight, width_weight, min_height, max_height
        )

    def update_layout(
        self,
        *,
        height_weight: float | _Unchanged = _Unchanged.VALUE,
        width_weight: float | _Unchanged = _Unchanged.VALUE,
        min_height: int | _Unchanged = _Unchanged.VALUE,
        max_height: int | None | _Unchanged = _Unchanged.VALUE,
    ) -> None:
        """Change only supplied expanded sizing options as one validated update.

        Omitted arguments retain their current values; unlike ``set_layout()``,
        ``update_layout(height_weight=2)`` preserves the width weight and both
        height bounds. Explicit
        ``max_height=None`` removes the upper bound. Validation uses the complete
        resulting layout, and failure leaves all settings unchanged. Collapsed
        state and its fixed height are preserved. Bounds describe physical
        content rows independently of responsive virtual size minimums; frames
        that cannot meet the minimums show the terminal-too-small view. Use the
        UI thread while the application is running.

        Args:
            height_weight: New finite positive relative share of expanded physical
                height, including two border rows per panel. Omission retains
                the current value. Integers and floats are accepted, excluding
                booleans.
            width_weight: New finite positive share of complete frame width
                within the row. Omission retains the current value.
            min_height: New positive integer minimum expanded content rows,
                excluding borders. Omission retains the current minimum;
                booleans and ``None`` are rejected.
            max_height: New positive integer maximum expanded content rows,
                excluding borders, and at least the resulting ``min_height``.
                Omission retains the current bound; explicit ``None`` removes
                it. Booleans are rejected.

        Raises:
            TypeError: If a supplied weight or height has an invalid type. Only
                ``max_height`` accepts ``None``.
            ValueError: If either resulting weight is nonpositive or nonfinite, a
                height is nonpositive, ``max_height`` is below ``min_height``, or
                the panel has been removed or is not registered in its menu.
        """
        self._menu._set_content_panel_layout(
            self,
            self._height_weight
            if isinstance(height_weight, _Unchanged)
            else height_weight,
            self._width_weight
            if isinstance(width_weight, _Unchanged)
            else width_weight,
            self._min_height if isinstance(min_height, _Unchanged) else min_height,
            self._max_height if isinstance(max_height, _Unchanged) else max_height,
        )

    @staticmethod
    def _validate_layout(
        height_weight: float,
        width_weight: float,
        min_height: int,
        max_height: int | None,
    ) -> None:
        for name, value in (
            ("height_weight", height_weight),
            ("width_weight", width_weight),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a finite positive number")
            if value <= 0 or (isinstance(value, float) and not isfinite(value)):
                raise ValueError(f"{name} must be a finite positive number")
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

    def move_left(self) -> None:
        """Exchange with the left neighbor, or do nothing at the row edge."""
        self._menu._move_content_panel_direction(self, "left")

    def move_right(self) -> None:
        """Exchange with the right neighbor, or do nothing at the row edge."""
        self._menu._move_content_panel_direction(self, "right")

    def move_up(self) -> None:
        """Insert into the preceding row at this column or its end."""
        self._menu._move_content_panel_direction(self, "up")

    def move_down(self) -> None:
        """Insert into the following row at this column or its end."""
        self._menu._move_content_panel_direction(self, "down")

    def swap_up(self) -> None:
        """Exchange with the same-column panel above, when present."""
        self._menu._move_content_panel_direction(self, "up", swap=True)

    def swap_down(self) -> None:
        """Exchange with the same-column panel below, when present."""
        self._menu._move_content_panel_direction(self, "down", swap=True)

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
