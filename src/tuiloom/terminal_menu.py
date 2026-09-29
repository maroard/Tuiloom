from __future__ import annotations

from collections.abc import Callable
from shutil import get_terminal_size
from time import monotonic
from typing import TYPE_CHECKING, Literal, cast

from wcwidth import iter_graphemes

from tuiloom._message_registry import MessageKey
from tuiloom.choice_layout import ChoiceLine, choice_lines
from tuiloom.command import (
    ChoiceCallback,
    ChoiceContext,
    ChoiceOption,
    CommandCallback,
    CommandContext,
    GlobalCommand,
    InputCallback,
    MenuChoice,
    MenuCommand,
)
from tuiloom.configuration import AutoScrollMode, MenuPresentation
from tuiloom.content_panel import ContentPanel
from tuiloom.event_loop.event_loop import EventLoop
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.key_binding import KeyBinding
from tuiloom.menu_display import MenuDisplay
from tuiloom.menu_interaction import AlertState, InputState
from tuiloom.output_task import OutputTaskSession
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.screen_content import ScreenContent
from tuiloom.status_bar import StatusBar
from tuiloom.task_exit import TaskExitAction, TaskExitState

if TYPE_CHECKING:
    from tuiloom.terminal_app import TerminalApp


class TerminalMenu:
    """Configure one application's commands, content panels and interactions.

    Create a menu, register its commands and panels, then open it through its
    application. Use ``app.set_main_menu(menu)`` to make it the default entry
    point. Mutation methods are intended for configuration before ``app.run()``
    or for callbacks on its UI thread. Producers run separately and should not
    mutate the menu directly.

    Inline presentation reserves rows for commands below the content panels.
    Overlay presentation places the command box over the panels without
    reducing their layout height. Menu visibility affects the command box,
    while the panels and optional bottom status line remain available.

    Attributes:
        app: Read-only reference to the owning application.
        display_state: Read-only reference to live appearance settings; mutate
            its fields to change titles, widths or footer text.
        commands: Read-only tuple snapshot of live user command and choice
            handles in display order, excluding Back/Quit. Use this menu's
            methods to add, remove, move or update commands.
        content_panels: Read-only tuple snapshot of live panel handles in display
            order. Add panels with ``add_content_panel()`` and mutate their
            handles to change, move or remove them.
        status_bar: Read-only reference to the installed ``StatusBar``, or
            ``None``. Use ``set_status_bar()`` or ``clear_status_bar()`` to change it.
        is_main: Read-only registration state changed by ``app.set_main_menu()``;
            it does not identify the currently visible menu.
        presentation: Read-only effective inline or overlay mode; an inherited
            mode is resolved again whenever the menu is opened.
        menu_visible: Read-only command-box visibility flag controlled by
            ``show_menu()``, ``hide_menu()`` and ``toggle_menu()``.
        active_message_key: Read-only registered persistent footer key, or
            ``None`` for raw text or no footer. Use ``show_message()``,
            ``toggle_message()`` or ``clear_message()`` to change it; temporary
            option previews leave it unchanged.
    """

    def __init__(
        self,
        app: TerminalApp,
        display_state: MenuDisplay,
        *,
        content_spacing: bool = True,
        presentation: MenuPresentation | None = None,
    ) -> None:
        """Create a menu and attach any application-wide initial content.

        This configures the menu without opening it or starting its workers.
        A global content factory, when configured on the application, is called
        once now on this constructor's thread, never on reopening. Its result
        becomes an ordinary panel owned by this menu.

        Args:
            app: Owning ``TerminalApp``; its navigation, keymap and global
                commands are shared with this menu. Menus from different
                applications cannot be linked.
            display_state: Mutable ``MenuDisplay`` object retained by reference.
            content_spacing: Insert one blank row between inline panels and
                commands. Must be a bool; defaults to ``True`` and is ignored
                in overlay presentation.
            presentation: Fixed ``"inline"``/``"overlay"`` mode, or ``None``
                (the default) to inherit the parent whenever opened and use
                inline when opened without a parent.

        Raises:
            TypeError: If ``display_state`` or ``content_spacing`` has an invalid
                type, or the global content factory returns non-``ScreenContent``.
            ValueError: If ``presentation`` is invalid, or an inherited stream
                is already mounted on another panel in this application.
            Exception: If the global content factory raises; its exception is
                propagated from this constructor without being wrapped.
        """
        if not isinstance(content_spacing, bool):
            raise TypeError("content_spacing must be a bool")
        if not isinstance(display_state, MenuDisplay):
            raise TypeError("display_state must be a MenuDisplay")
        self._app = app
        self._display_state = display_state
        self._content_spacing = content_spacing
        if presentation not in (None, "inline", "overlay"):
            raise ValueError("presentation must be 'inline', 'overlay', or None")
        self._configured_presentation = presentation
        self._presentation: MenuPresentation = presentation or "inline"
        self._menu_visible = True
        self._commands: list[MenuCommand] = []
        self._exit_label = "Back"
        self._exit_label_explicit = False
        self._selected_index = 0
        self._choice_index: int | None = None
        self._focused_panel: ContentPanel | None = None
        self._running = False
        self._hard_exit_requested = False

        self._input: InputState | None = None
        self._alert: AlertState | None = None

        self._output_task_session: OutputTaskSession | None = None
        self._output_task_panel: ContentPanel | None = None
        self._disabled_messages: set[str] = set()
        self._disabled_global_commands: set[GlobalCommand] = set()
        self._global_overrides: dict[GlobalCommand, CommandCallback] = {}
        self._task_exit: TaskExitState | None = None

        self._menu_renderer: MenuRenderer | None = None
        self._terminal_renderer: TerminalRenderer | None = None
        self._event_loop: EventLoop | None = None
        self._status_bar: StatusBar | None = None
        self._status_bar_revision = 0
        self._content_panels: list[ContentPanel] = []
        inherited_content = app._create_global_content()
        if inherited_content is not None:
            self.add_content_panel(inherited_content)

    @property
    def app(self) -> TerminalApp:
        """Access the application that owns this menu.

        Returns:
            The original application reference; this property is read-only.
        """
        return self._app

    @property
    def display_state(self) -> MenuDisplay:
        """Access the live appearance settings supplied at construction.

        Change fields on this object to update the title, widths or footer.
        The reference itself cannot be replaced through this property.

        Returns:
            The original mutable ``MenuDisplay`` object, not a copy.
        """
        return self._display_state

    @property
    def commands(self) -> tuple[MenuCommand, ...]:
        """Inspect user commands in their current display order.

        Returns:
            A tuple snapshot of command and choice handles, including disabled
            commands and excluding the automatic Back/Quit option. Handles
            remain live; use menu mutation methods to change them.
        """
        return tuple(self._commands)

    @property
    def content_panels(self) -> tuple[ContentPanel, ...]:
        """Inspect the currently registered content panels in display order.

        Returns:
            A tuple snapshot of live panel handles, including any temporary
            output-task panel and excluding panels already removed.
        """
        return tuple(self._content_panels)

    @property
    def status_bar(self) -> StatusBar | None:
        """Inspect the optional status line at the bottom of the terminal.

        Returns:
            The installed ``StatusBar`` configuration, or ``None``. Install or
            replace it with ``set_status_bar()``; remove it with
            ``clear_status_bar()``.
        """
        return self._status_bar

    def set_status_bar(self, content: str | StatusBar) -> None:
        """Install or replace the status line and request a new frame.

        The line reserves one terminal row independently of menu visibility.
        Dynamic and responsive providers are evaluated on the UI thread during
        rendering, rather than by this call; keep them quick and non-blocking.
        Newlines are removed, tabs expand to eight-cell stops from column zero,
        and text is clipped to the full terminal width without wrapping. Safe
        SGR styles and HTTP(S) hyperlinks remain; other controls are removed.

        Args:
            content: A static text string, or a ``StatusBar`` created with its
                ``static()``, ``dynamic()`` or ``responsive()`` factory.

        Raises:
            TypeError: If ``content`` is neither a string nor ``StatusBar``.
        """
        if isinstance(content, str):
            content = StatusBar.static(content)
        if not isinstance(content, StatusBar):
            raise TypeError("status content must be a str or StatusBar")
        self._status_bar = content
        self._status_bar_changed()

    def clear_status_bar(self) -> None:
        """Remove the status line and request a frame using the freed row.

        Calling this when no status bar is installed is harmless. Content
        sources continue running and receive any resulting layout changes.
        """
        self._status_bar = None
        self._status_bar_changed()

    def refresh_status_bar(self) -> None:
        """Request responsive status reevaluation even if width is unchanged.

        The provider runs on the UI thread when the next frame is drawn, not
        synchronously inside this method.

        Raises:
            RuntimeError: If no status bar is installed or its factory was not
                ``StatusBar.responsive()``.
        """
        if self._status_bar is None or self._status_bar._kind != "responsive":
            raise RuntimeError("Only responsive status can be refreshed")
        self._status_bar_changed()

    def _status_bar_changed(self) -> None:
        self._status_bar_revision += 1
        self._invalidate_renderer()
        if self._event_loop is not None:
            self._event_loop.request_render(immediate=True)

    @property
    def is_main(self) -> bool:
        """Check whether this menu is the application's configured main menu.

        This identifies registration through ``app.set_main_menu()``; a menu
        passed as an explicit entry to ``app.run(menu)`` need not be registered.

        Returns:
            ``True`` if ``app.main_menu`` is this menu, otherwise ``False``.
        """
        return self is self.app.main_menu

    @property
    def presentation(self) -> MenuPresentation:
        """Inspect the effective inline or overlay presentation.

        An inherited mode is resolved each time the menu is opened. Before its
        first opening, an unconfigured menu reports ``"inline"``.

        Returns:
            ``"inline"`` for a command box below the panels, or ``"overlay"``
            for a box drawn over their full-height layout.
        """
        return self._presentation

    def _resolve_presentation(self, parent: TerminalMenu | None) -> None:
        self._presentation = self._configured_presentation or (
            parent.presentation if parent is not None else "inline"
        )

    @property
    def menu_visible(self) -> bool:
        """Check whether the command box is configured to be visible.

        Returns:
            ``True`` after ``show_menu()`` and ``False`` after ``hide_menu()``.
            Background-task exit controls may still be shown during shutdown
            even when this value is ``False``.
        """
        return self._menu_visible

    @property
    def _menu_box_visible(self) -> bool:
        # Root shutdown choices must be usable even on a hidden dashboard menu.
        return self._menu_visible or self._task_exit is not None

    def show_menu(self) -> None:
        """Reveal a hidden command box, focus it and request a new frame.

        Existing command selection, choice preview, alert and input buffer are
        preserved. Calling this on an already visible box has no effect and
        does not change focus.
        """
        if self._menu_visible:
            return
        self._menu_visible = True
        self._focused_panel = None
        self._request_menu_render()

    def hide_menu(self) -> None:
        """Hide the command box while leaving panels and status available.

        Alerts and input buffers are preserved but cannot be interacted with
        through the hidden box. Focus moves to a content panel when available;
        workers continue running. Global bindings remain available. Calling
        this on an already hidden box has no effect.
        """
        if not self._menu_visible:
            return
        self._menu_visible = False
        self._normalize_focus()
        self._request_menu_render()

    def toggle_menu(self) -> None:
        """Switch command-box visibility while preserving interaction state.

        Hiding keeps panels, status and workers active. Revealing the box gives
        it focus. The change is rendered by the application on a later frame.
        """
        if self._menu_visible:
            self.hide_menu()
        else:
            self.show_menu()

    def _request_menu_render(self) -> None:
        # Retain previous composed lines so closing the box restores by diff.
        if self._event_loop is not None:
            self._event_loop.request_render(immediate=True)

    def add_content_panel(
        self,
        content: ScreenContent,
        *,
        description: str = "Content in progress",
        auto_scroll: AutoScrollMode | None = None,
        position: int | None = None,
        weight: float = 1,
        min_height: int = 1,
        max_height: int | None = None,
        collapsed_height: int = 1,
    ) -> ContentPanel:
        """Register independent content and return its stable panel handle.

        Sources start immediately if this menu has an initialized runtime;
        otherwise they start when it is first opened. Collapsing or hiding the
        panel's menu does not stop its source. Mutate the returned handle to
        replace content, change layout, reorder or remove the panel.

        Args:
            content: ``ScreenContent`` created by a static, lines, stream,
                dynamic or responsive factory. A single stream iterator cannot
                be mounted concurrently in two panels of this application.
            description: Panel label and text identifying active work during
                shutdown. Defaults to ``"Content in progress"``.
            auto_scroll: ``None`` for manual scrolling (default), ``"smart"``
                to follow new stream batches until the user scrolls upward, or
                ``"strict"`` to follow every new batch despite manual scrolling.
            position: Zero-based insertion index among panels; ``None`` appends.
                The current panel count is a valid insertion index.
            weight: Positive finite relative share of available total panel rows,
                including borders. Defaults to ``1``.
            min_height: Minimum desired content rows, excluding borders. Must
                be a positive integer; defaults to ``1``. If panel minimums
                cannot fit, a terminal-too-small view replaces the normal layout.
            max_height: Maximum content rows, excluding borders; ``None`` leaves
                the height uncapped. Otherwise an integer at least ``min_height``.
            collapsed_height: Positive number of content rows displayed when
                collapsed. Defaults to ``1``; the panel is initially expanded.

        Returns:
            The registered ``ContentPanel`` handle. Its identity is preserved
            by replacements and moves; removal invalidates mutation operations.

        Raises:
            TypeError: If ``content`` is not ``ScreenContent``, ``position`` is
                not an integer or ``None``, or a sizing value has an invalid
                type. Booleans are not accepted as numeric sizing values.
            ValueError: If the insertion index, auto-scroll mode or sizing bounds
                are invalid, or the stream is already owned by another panel.
        """
        self._validate_auto_scroll(auto_scroll)
        insert_at = self._validate_content_position(position, allow_end=True)
        if not isinstance(content, ScreenContent):
            raise TypeError("content must be a ScreenContent")
        panel = ContentPanel(
            self,
            content,
            description,
            auto_scroll,
            weight=weight,
            min_height=min_height,
            max_height=max_height,
            collapsed_height=collapsed_height,
        )
        self.app._claim_stream(content, panel)
        self._content_panels.insert(insert_at, panel)
        self._normalize_focus()
        if self._running and self._event_loop is not None:
            self._event_loop.add_content_panel(panel)
        self._invalidate_renderer()
        return panel

    def _set_content_panel_content(
        self,
        panel: ContentPanel,
        content: ScreenContent,
    ) -> None:
        """Replace one owned panel's content without changing its identity."""
        self._require_content_panel(panel)
        if not isinstance(content, ScreenContent):
            raise TypeError("content must be a ScreenContent")
        self.app._claim_stream(content, panel)
        panel._runtime.smart_auto_scroll_active = True
        panel._runtime.pending_auto_scroll = None
        if self._running and self._event_loop is not None:
            self._event_loop.replace_content_panel(panel, content)
        else:
            panel._content = content
            panel._runtime.mount(content)
        self.app._prune_stream_claims(panel)
        self._invalidate_renderer()

    def _refresh_content_panel(self, panel: ContentPanel) -> None:
        """Force one responsive panel to produce a new value."""
        self._require_content_panel(panel)
        if panel._content._kind != "responsive":
            raise RuntimeError("Only responsive content can be refreshed")
        panel._runtime.responsive_refresh_pending = True
        if self._running and self._event_loop is not None:
            self._event_loop.refresh_content_panel(panel)
        self._invalidate_renderer()

    def _set_content_panel_description(
        self,
        panel: ContentPanel,
        description: str,
    ) -> None:
        """Replace the visible and shutdown description of one panel."""
        self._require_content_panel(panel)
        panel._description = description
        if panel._runtime.worker is not None:
            panel._runtime.worker.description = description
        self._invalidate_renderer()

    def _set_content_panel_auto_scroll(
        self,
        panel: ContentPanel,
        mode: AutoScrollMode | None,
    ) -> None:
        """Set one panel's iterator auto-scroll policy."""
        self._require_content_panel(panel)
        self._validate_auto_scroll(mode)
        panel._auto_scroll = mode
        panel._runtime.smart_auto_scroll_active = True
        panel._runtime.pending_auto_scroll = None

    def _set_content_panel_layout(
        self,
        panel: ContentPanel,
        weight: float,
        min_height: int,
        max_height: int | None,
    ) -> None:
        """Validate and atomically replace an owned panel's sizing options."""
        self._require_content_panel(panel)
        panel._validate_layout(weight, min_height, max_height)
        panel._weight = weight
        panel._min_height = min_height
        panel._max_height = max_height
        self._invalidate_renderer()
        if self._running and self._event_loop is not None:
            self._event_loop.request_render(immediate=True)

    def _set_content_panel_collapsed(
        self, panel: ContentPanel, collapsed: bool
    ) -> None:
        """Change an owned panel's display state without touching its runtime."""
        self._require_content_panel(panel)
        if panel._collapsed == collapsed:
            return
        panel._collapsed = collapsed
        self._invalidate_renderer()
        if self._running and self._event_loop is not None:
            self._event_loop.request_render(immediate=True)

    def _set_content_panel_collapsed_height(
        self, panel: ContentPanel, height: int
    ) -> None:
        """Validate and replace an owned panel's fixed collapsed height."""
        self._require_content_panel(panel)
        panel._validate_collapsed_height(height)
        panel._collapsed_height = height
        self._invalidate_renderer()
        if self._running and self._event_loop is not None:
            self._event_loop.request_render(immediate=True)

    def _move_content_panel(self, panel: ContentPanel, position: int) -> None:
        """Move one owned panel to a zero-based position."""
        self._require_content_panel(panel)
        target = self._validate_content_position(position, allow_end=False)
        self._content_panels.remove(panel)
        self._content_panels.insert(target, panel)
        self._invalidate_renderer()

    def _remove_content_panel(self, panel: ContentPanel) -> None:
        """Remove one owned panel and cooperatively retire its worker."""
        self._require_content_panel(panel)
        removed_position = self._content_panels.index(panel)
        was_focused = panel is self._focused_panel
        self._content_panels.remove(panel)
        panel._removed = True
        if self._running and self._event_loop is not None:
            self._event_loop.retire_content_panel(panel)
        else:
            self.app._release_stream_claims(panel)
        if was_focused:
            self._focused_panel = (
                self._content_panels[removed_position]
                if removed_position < len(self._content_panels)
                else None
            )
        self._normalize_focus()
        self._invalidate_renderer()

    def add_command(
        self,
        label: str,
        callback: CommandCallback,
        *,
        on_hover: CommandCallback | None = None,
        position: int | None = None,
    ) -> MenuCommand:
        """Register a selectable action without executing its callbacks.

        Activation invokes ``callback(context)`` on the UI thread. The return
        value is ignored; use the context's menu/application to update the UI or
        navigate. Keep callbacks short; use ``start_output_task()`` for blocking
        work. A callback exception propagates through the application loop.

        Args:
            label: Visible command text.
            callback: Callable taking one ``CommandContext`` when activated.
                The context contains this app, menu, command and triggering key.
            on_hover: Optional callable taking ``CommandContext`` when keyboard
                selection reaches this command, including initial selection when
                opening the menu. ``binding`` is ``None`` for that initial call.
                Initial opening precedes the menu's first runtime initialization,
                so it cannot start an output task yet. This is keyboard selection,
                not a mouse event.
            position: Zero-based insertion index among user commands, excluding
                Back/Quit. ``None`` appends before Back/Quit; the current command
                count is a valid insertion index.

        Returns:
            A stable ``MenuCommand`` handle, initially enabled. Use this menu's
            mutation methods to rename, move, disable or remove it.

        Raises:
            TypeError: If a callback is not callable, or ``position`` is neither
                an integer nor ``None``. A bool is not a valid position.
            ValueError: If ``position`` is outside the insertion range.
        """
        if not callable(callback):
            raise TypeError("callback must be callable")
        insert_at = self._validate_position(position, allow_end=True)
        selected = (
            self._commands[self._selected_index]
            if self._selected_index < len(self._commands)
            else None
        )
        command = MenuCommand(self, label, callback, on_hover)
        self._commands.insert(insert_at, command)
        if selected is not None:
            self._selected_index = self._commands.index(selected)
        self._normalize_selection()
        return command

    def add_choice(
        self,
        label: str,
        options: list[ChoiceOption] | tuple[ChoiceOption, ...],
        on_select: ChoiceCallback,
        *,
        rows: int = 1,
        selected_index: int = 0,
        on_hover: CommandCallback | None = None,
        position: int | None = None,
    ) -> MenuChoice:
        """Register an option selector with separate preview and committed state.

        Keyboard navigation previews options without changing the committed
        index. Activating an option commits it before calling ``on_select`` on
        the UI thread. Activating the choice label enters option navigation.
        Programmatic ``set_choice_index()`` changes the committed selection
        without invoking callbacks. Callback return values are ignored and
        exceptions propagate through the application loop.

        Args:
            label: Visible text identifying the selector.
            options: Nonempty list or tuple of ``ChoiceOption`` objects, copied
                into an immutable tuple. Each option's ``row`` must be in
                ``0..rows-1`` and any ``hover_message`` key must be registered.
            on_select: Callable taking ``ChoiceContext`` for the newly committed
                option. The context includes the option, its original index and
                triggering key binding, together with app, menu and choice.
            rows: Positive count of logical option rows. Defaults to ``1``;
                rendering may wrap each logical row to fit available width.
            selected_index: Initial committed zero-based index in ``options``.
                Defaults to ``0``; construction does not invoke ``on_select``.
            on_hover: Optional command-level callable taking ``CommandContext``
                when keyboard selection reaches the choice label, including
                initial opening with ``binding=None``. Option-level previews
                use each ``ChoiceOption.on_hover`` with ``ChoiceContext``. The
                initial callback precedes the menu's first runtime initialization
                and cannot start an output task yet.
            position: Zero-based insertion index among user commands, excluding
                Back/Quit. ``None`` appends; the command count is valid.

        Returns:
            An initially enabled ``MenuChoice`` handle exposing committed
            ``selected_index``, ``selected_option`` and ``selected_label``.

        Raises:
            TypeError: If ``on_select`` or ``on_hover`` is not callable, or
                ``position`` is neither an integer nor ``None`` (bool excluded).
            ValueError: If options are empty or contain non-``ChoiceOption``
                objects, rows or option rows are invalid, ``selected_index`` is
                invalid, or ``position`` is outside the insertion range.
            KeyError: If an option's ``hover_message`` key is not registered.
        """
        if not callable(on_select):
            raise TypeError("on_select must be callable")
        insert_at = self._validate_position(position, allow_end=True)
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
            raise ValueError("rows must be a positive integer")
        if not options or any(
            not isinstance(option, ChoiceOption) for option in options
        ):
            raise ValueError("options must be a nonempty list of ChoiceOption")
        if any(
            isinstance(option.row, bool)
            or not isinstance(option.row, int)
            or option.row < 0
            or option.row >= rows
            for option in options
        ):
            raise ValueError("option row is outside declared rows")
        if (
            isinstance(selected_index, bool)
            or not isinstance(selected_index, int)
            or not 0 <= selected_index < len(options)
        ):
            raise ValueError("selected_index is outside options")
        for option in options:
            if option.hover_message is not None:
                self.app._validate_message_key(option.hover_message)
        selected = (
            self._commands[self._selected_index]
            if self._selected_index < len(self._commands)
            else None
        )
        choice = MenuChoice(
            self, label, tuple(options), rows, selected_index, on_select, on_hover
        )
        self._commands.insert(insert_at, choice)
        if selected is not None:
            self._selected_index = self._commands.index(selected)
        self._normalize_selection()
        return choice

    def set_choice_index(self, choice: MenuChoice, selected_index: int) -> None:
        """Set the committed option without invoking selection or hover callbacks.

        This updates the displayed selected value and requests a redraw. Any
        current keyboard preview remains independent of the committed index.

        Args:
            choice: Registered ``MenuChoice`` owned by this menu.
            selected_index: Zero-based index in ``choice.options``. Must be an
                integer other than bool and lie within the option tuple.

        Raises:
            ValueError: If the handle is removed, foreign or not a choice, or
                ``selected_index`` is not a valid option index.
        """
        self._require_command(choice)
        if not isinstance(choice, MenuChoice):
            raise ValueError("Command is not a choice")
        if (
            isinstance(selected_index, bool)
            or not isinstance(selected_index, int)
            or not 0 <= selected_index < len(choice.options)
        ):
            raise ValueError("selected_index is outside options")
        choice._selected_index = selected_index
        self._invalidate_renderer()

    def set_choice_callback(self, choice: MenuChoice, callback: ChoiceCallback) -> None:
        """Replace a choice's selection callback without changing its selection.

        The callback is not invoked by this call. Future keyboard commits and
        explicit calls to the choice's activation adapter use the replacement.

        Args:
            choice: Registered ``MenuChoice`` owned by this menu.
            callback: Callable accepting one ``ChoiceContext``. Keyboard
                activation runs it on the UI thread; its return value is ignored.

        Raises:
            ValueError: If the handle is removed, foreign or not a choice.
            TypeError: If ``callback`` is not callable.
        """
        self._require_command(choice)
        if not isinstance(choice, MenuChoice):
            raise ValueError("Command is not a choice")
        if not callable(callback):
            raise TypeError("callback must be callable")
        choice._on_select = callback

    def add_submenu(
        self,
        submenu: TerminalMenu,
        label: str,
        *,
        on_hover: CommandCallback | None = None,
        position: int | None = None,
    ) -> MenuCommand:
        """Register an action that opens another menu when activated.

        Registration itself does not navigate or start workers. Activation
        calls ``app.push_menu(submenu)``; its presentation inherits this menu's
        mode if not explicitly configured. Back returns to the parent while
        initialized submenu workers continue running.

        Args:
            submenu: Menu belonging to the same application.
            label: Visible text for the action opening that menu.
            on_hover: Optional callable taking ``CommandContext`` on the UI
                thread when keyboard selection reaches this action. Initial
                opening can invoke it with ``binding=None`` before the menu's
                first runtime initialization, so it cannot start an output task.
            position: Zero-based insertion index among user commands; ``None``
                appends before Back/Quit. The current command count is valid.

        Returns:
            The registered ``MenuCommand`` handle, not the submenu.

        Raises:
            ValueError: If the submenu belongs to another application or the
                insertion index is outside its valid range.
            TypeError: If ``on_hover`` is not callable, or ``position`` is not
                an integer or ``None`` (bool excluded).
        """
        if submenu.app is not self.app:
            raise ValueError("Submenu must belong to the same TerminalApp")
        return self.add_command(
            label,
            lambda context: context.app.push_menu(submenu),
            on_hover=on_hover,
            position=position,
        )

    def set_command_label(self, command: MenuCommand, label: str) -> None:
        """Rename a registered command or choice while preserving its identity.

        Args:
            command: User command or choice currently owned by this menu.
            label: New visible text. Position, enabled state and callbacks stay
                the same; the next frame uses the new label.

        Raises:
            ValueError: If the command is foreign, removed or not a menu command.
        """
        self._require_command(command)
        command._label = label

    def remove_command(self, command: MenuCommand) -> None:
        """Remove a command or choice and stop accepting its handle for mutation.

        If selected, selection moves to a nearby enabled command or Back/Quit
        and any option preview is cleared. Callbacks are not invoked. The
        automatic Back/Quit action is not a removable user command.

        Args:
            command: User command or choice currently registered in this menu.

        Raises:
            ValueError: If the handle is foreign, already removed or invalid.
        """
        self._require_command(command)
        removed_position = self._commands.index(command)
        selected = (
            self._commands[self._selected_index]
            if self._selected_index < len(self._commands)
            else None
        )
        self._commands.pop(removed_position)
        if selected is not command:
            self._selected_index = (
                self._commands.index(selected)
                if selected is not None
                else len(self._commands)
            )
            return

        self._choice_index = None
        for index in range(removed_position, len(self._commands)):
            if self._commands[index].enabled:
                self._selected_index = index
                return
        for index in range(removed_position - 1, -1, -1):
            if self._commands[index].enabled:
                self._selected_index = index
                return
        self._selected_index = len(self._commands)

    def set_command_callback(
        self, command: MenuCommand, callback: CommandCallback
    ) -> None:
        """Replace a regular command's activation callback without invoking it.

        The command retains its identity, label, position and enabled state.
        For a ``MenuChoice``, use ``set_choice_callback()`` instead: that callback
        receives a ``ChoiceContext`` rather than a ``CommandContext``.

        Args:
            command: Registered ordinary ``MenuCommand`` owned by this menu.
            callback: Callable accepting one ``CommandContext`` on activation.
                Keyboard activation runs it on the UI thread and ignores its
                return value.

        Raises:
            ValueError: If the handle is foreign, removed or a ``MenuChoice``.
            TypeError: If ``callback`` is not callable.
        """
        self._require_command(command)
        if isinstance(command, MenuChoice):
            raise ValueError("Use set_choice_callback for a MenuChoice")
        if not callable(callback):
            raise TypeError("callback must be callable")
        command._callback = callback

    def move_command(self, command: MenuCommand, position: int) -> None:
        """Move a registered command or choice while preserving the selected handle.

        Validation precedes mutation. Positions count only user commands,
        including disabled ones, and exclude the automatic Back/Quit action.

        Args:
            command: User command or choice currently owned by this menu.
            position: Desired final zero-based index, from ``0`` to
                ``len(menu.commands) - 1``.

        Raises:
            ValueError: If the handle is foreign or removed, or the position is
                outside the current command range.
            TypeError: If ``position`` is not an integer, or is bool.
        """
        self._require_command(command)
        if isinstance(position, bool) or not isinstance(position, int):
            raise TypeError("Command position must be an integer")
        if position < 0 or position >= len(self._commands):
            raise ValueError("Command position is outside the menu")
        selected = (
            self._commands[self._selected_index]
            if self._selected_index < len(self._commands)
            else None
        )
        old = self._commands.index(command)
        self._commands.pop(old)
        self._commands.insert(position, command)
        self._selected_index = (
            self._commands.index(selected)
            if selected is not None
            else len(self._commands)
        )
        self._normalize_selection()

    def disable_command(self, command: MenuCommand) -> None:
        """Keep a command visible while preventing selection and activation.

        Selection moves to an enabled item if needed. Disabling an already
        disabled item is harmless; its position and callbacks are retained.

        Args:
            command: User command or choice currently owned by this menu.

        Raises:
            ValueError: If the handle is foreign, removed or invalid.
        """
        self._require_command(command)
        command._enabled = False
        self._normalize_selection()

    def enable_command(self, command: MenuCommand) -> None:
        """Make a registered command or choice selectable and activatable again.

        Enabling an already enabled item is harmless and does not activate it.

        Args:
            command: User command or choice currently owned by this menu.

        Raises:
            ValueError: If the handle is foreign, removed or invalid.
        """
        self._require_command(command)
        command._enabled = True
        self._normalize_selection()

    def set_exit_label(self, label: str) -> None:
        """Set a persistent custom label for the automatic final exit action.

        The action keeps its Back/Quit behavior. Subsequent navigation does not
        replace this explicit label with the automatic root/child default.

        Args:
            label: Visible text for the final action, normally Quit at the root
                or Back in a child menu.
        """
        self._exit_label = label
        self._exit_label_explicit = True

    def set_global_command_callback(
        self, command: GlobalCommand, callback: CommandCallback
    ) -> None:
        """Override a global shortcut's callback only while this menu is active.

        Its key binding and label remain shared with the application. Other
        menus continue using their own override or the application callback.

        Args:
            command: ``GlobalCommand`` owned by this menu's application.
            callback: Replacement callable taking ``CommandContext`` with this
                menu and the global-command handle. It runs on the UI thread
                when the shortcut is handled; its return value is ignored.

        Raises:
            ValueError: If ``command`` does not belong to this application.
            TypeError: If ``callback`` is not callable.
        """
        self.app._require_global(command)
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._global_overrides[command] = callback

    def clear_global_command_callback(self, command: GlobalCommand) -> None:
        """Restore a global shortcut's application callback for this menu.

        Clearing an absent override is harmless. This changes neither the
        command's binding nor its local enabled/disabled state.

        Args:
            command: ``GlobalCommand`` owned by this menu's application.

        Raises:
            ValueError: If ``command`` does not belong to this application.
        """
        self.app._require_global(command)
        self._global_overrides.pop(command, None)

    def disable_global_command(self, command: GlobalCommand) -> None:
        """Prevent this menu from invoking one application's global shortcut.

        The binding remains reserved application-wide; disabling does not make
        it available for another shortcut or keymap action. Other menus are
        unaffected, and any local callback override is retained.

        Args:
            command: ``GlobalCommand`` owned by this menu's application.

        Raises:
            ValueError: If ``command`` does not belong to this application.
        """
        self.app._require_global(command)
        self._disabled_global_commands.add(command)

    def enable_global_command(self, command: GlobalCommand) -> None:
        """Remove this menu's suppression of a global shortcut.

        Calling this on an already enabled command is harmless. A retained
        local callback override becomes active again; otherwise the application's
        callback is used. Input entry can still consume the shortcut's keys.

        Args:
            command: ``GlobalCommand`` owned by this menu's application.

        Raises:
            ValueError: If ``command`` does not belong to this application.
        """
        self.app._require_global(command)
        self._disabled_global_commands.discard(command)

    def start_output_task[T](
        self,
        action: Callable[[], T],
        *,
        on_success: Callable[[T], None],
        on_error: Callable[[Exception], None],
        description: str = "Task in progress",
    ) -> None:
        """Start background work and display its captured output in a temporary panel.

        This call returns immediately with no task handle. The action runs in a
        non-daemon thread; exactly one outcome callback is dispatched on the UI
        thread after it terminates during normal application operation. The
        panel is removed after its buffered output drains, so it may still be
        present when the callback runs. Callback exceptions propagate through
        the application loop; callbacks are discarded during shutdown.

        Capture includes Python stdout/stderr writes from all non-UI threads
        while the action runs, including independent workers. Subprocess output
        and direct file-descriptor writes are excluded. Only one captured task
        can be active per application. This menu must already have an initialized
        active runtime, although another menu can currently be visible. The
        action cannot be forcibly interrupted independently of the process;
        normal shutdown waits for it, while Force quit restores the terminal
        and terminates the application process.

        Args:
            action: Zero-argument callable executed in the background thread.
                Its return value is passed to ``on_success``. Do not mutate the
                UI here; use an outcome callback on the UI thread instead.
            on_success: Callable taking the action's result, including ``None``
                if the action has no result. Its own return value is ignored.
            on_error: Callable taking the action's exception. ``BaseException``
                subclasses outside ``Exception`` are wrapped in ``RuntimeError``
                with the original exception as their cause. Return is ignored.
            description: Temporary panel label and identifier in exit controls.
                Defaults to ``"Task in progress"``; its stream follows output
                with strict automatic scrolling.

        Raises:
            RuntimeError: If this menu has no active initialized runtime,
                another captured task is active in the application, or the
                action's worker thread cannot be started.
        """
        if not self._running or self._event_loop is None:
            raise RuntimeError("Output tasks can only run while the menu is active")
        if self._output_task_session is not None:
            raise RuntimeError("Another output task is already running")

        def complete(result: object) -> None:
            on_success(cast(T, result))

        try:
            session = self.app._start_output_task(
                self, action, complete, on_error, description
            )
            self._output_task_session = session
            panel = self.add_content_panel(
                ScreenContent.stream(session.iter_output()),
                description=description,
                auto_scroll="strict",
            )
            self._output_task_panel = panel
            self.app._attach_output_panel(session, panel)
        except BaseException:
            self._output_task_session = None
            self._output_task_panel = None
            raise

    def enter_input_mode(
        self,
        prompt: str,
        callback: InputCallback,
        *,
        hidden: bool = False,
    ) -> None:
        """Start or replace text entry with an empty Unicode buffer.

        The activation binding (Enter by default) submits the buffer but keeps
        the session and text until ``leave_input_mode()`` is called. The Back
        binding (Escape by default) discards the session. Unmodified Backspace
        deletes one grapheme. While the visible command box accepts input, it
        consumes text and bindings, including global shortcuts. An alert can
        suspend the input and preserve its buffer. Opening this menu with
        ``push_menu()``, ``replace_menu()`` or ``reset_to()`` resets the buffer;
        returning to it through Back preserves the existing buffer.

        Args:
            prompt: Text displayed immediately before the input buffer.
            callback: Callable taking the complete input string on the UI thread
                each time it is submitted. Its return value is ignored and its
                exceptions propagate through the application loop. It may call
                ``leave_input_mode()`` or start a replacement input session.
            hidden: Whether to mask each grapheme visually. Defaults to
                ``False``; masking does not encrypt the buffer and the callback
                still receives the original plain-text value.

        Raises:
            TypeError: If ``callback`` is not callable.
        """
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._input = InputState(prompt, callback, hidden)

    def leave_input_mode(self) -> None:
        """Discard the input session, including its prompt and current buffer.

        No input callback is invoked. Calling this outside input mode is
        harmless. An independent alert, if present, remains displayed.
        """
        self._input = None

    def show_alert(
        self,
        text: str,
        *,
        on_confirm: CommandCallback | None = None,
        prompt: str | None = None,
    ) -> None:
        """Replace the command-box body with an alert, preserving menu state.

        The alert suspends any input session without losing its buffer. Content
        panels keep running and global shortcuts remain available. The Back
        binding retains navigation/exit behavior; it does not simply dismiss
        the alert. Install a confirmation callback or call ``clear_alert()``
        programmatically to dismiss it.

        Args:
            text: Alert body text; a new call replaces any existing alert.
            on_confirm: Optional callable taking ``CommandContext`` when the
                activation binding (Enter by default) is pressed. It runs on
                the UI thread with ``command=None`` and the triggering binding.
                The alert is cleared after normal return; if it raises, the
                exception propagates and automatic clearing does not occur.
                ``None`` disables activation-based confirmation.
            prompt: Confirmation hint displayed below the body. ``None`` uses
                ``"Press Enter to continue"`` when a callback is provided, and
                no hint otherwise. A custom hint does not enable confirmation.
        """
        alert_prompt = (
            prompt
            if prompt is not None
            else "Press Enter to continue"
            if on_confirm is not None
            else None
        )
        self._alert = AlertState(text, on_confirm, alert_prompt)

    def clear_alert(self) -> None:
        """Dismiss the alert and reveal the preserved menu or input session.

        A suspended input keeps its prompt and buffer. No confirmation callback
        is invoked; calling this without an alert is harmless.
        """
        self._alert = None

    @property
    def active_message_key(self) -> str | None:
        """Identify the persistent registered message selected for this footer.

        Temporary option hover messages can visually replace the footer without
        changing this key. Directly assigning ``display_state.message`` clears
        its association with a registered key.

        Returns:
            The registered key set by ``show_message()`` or automatic messages,
            or ``None`` when the footer is raw text or empty.
        """
        return self.display_state._active_message_key

    def toggle_message(self, key: str) -> bool:
        """Toggle a registered persistent footer message.

        If this key is active, clear the footer even when the key has since been
        disabled. Otherwise show it only when enabled locally and globally.
        Suppression leaves an existing different footer unchanged.

        Args:
            key: Registered built-in ``MessageKey`` or custom string key added
                with ``app.add_message()``.

        Returns:
            ``True`` when the requested message is selected for display;
            ``False`` when it was hidden or suppression prevented showing it.

        Raises:
            KeyError: If ``key`` is unknown. The footer is left unchanged.
        """
        self.app._validate_message_key(key)
        if self.active_message_key == key:
            self.clear_message()
            return False
        return self.show_message(key)

    def show_message(self, key: str) -> bool:
        """Select an enabled registered message as the persistent footer.

        Existing footer text is retained if local or application-wide
        suppression prevents showing this message. Option hover previews may
        temporarily cover it without changing the active key.

        Args:
            key: Registered built-in ``MessageKey`` or custom string key added
                with ``app.add_message()``.

        Returns:
            ``True`` if the footer was set; ``False`` if the message is disabled
            or has no resolved text.

        Raises:
            KeyError: If ``key`` is unknown. The footer is left unchanged.
        """
        self.app._validate_message_key(key)
        if not self.is_message_enabled(key):
            return False
        message = self._message_text(key)
        if message is None:
            return False
        self.display_state._set_registered_message(key, message)
        return True

    def _message_text(self, key: str) -> str | None:
        context: dict[str, object] = {}
        if key == MessageKey.NO_CONTENT_SOURCE:
            context["menu_name"] = self.display_state.menu_name
        elif key == MessageKey.UNKNOWN_COMMAND:
            context["command"] = ""
        return self.app._get_message(key, **context)

    def _hover_message(self) -> str | None:
        """Resolve an option preview without changing the persistent footer."""
        if (
            self._focused_panel is not None
            or self._alert is not None
            or self._input is not None
        ):
            return None
        choice = self._active_choice()
        if choice is None or self._choice_index is None:
            return None
        key = choice.options[self._choice_index].hover_message
        if key is None or not self.is_message_enabled(key):
            return None
        return self._message_text(key)

    def clear_message(self) -> None:
        """Clear the persistent footer text and its registered message key.

        This does not disable any message or prevent a later automatic message.
        An active option hover preview is independent and may remain visible.
        """
        self.display_state.message = None

    def disable_message(self, key: str) -> None:
        """Suppress future display of a registered message in this menu.

        Other menus are unaffected. An already selected persistent footer is
        not cleared; use ``clear_message()`` or ``toggle_message()`` to hide it.

        Args:
            key: Registered built-in ``MessageKey`` or custom string key.

        Raises:
            KeyError: If ``key`` is not registered in the application.
        """
        self.app._validate_message_key(key)
        self._disabled_messages.add(key)

    def enable_message(self, key: str) -> None:
        """Remove this menu's suppression of a registered message.

        This does not display the message or override application-wide
        suppression. Enabling an already locally enabled message is harmless.

        Args:
            key: Registered built-in ``MessageKey`` or custom string key.

        Raises:
            KeyError: If ``key`` is not registered in the application.
        """
        self.app._validate_message_key(key)
        self._disabled_messages.discard(key)

    def is_message_enabled(self, key: str) -> bool:
        """Check whether a registered message can be shown in this menu.

        Args:
            key: Registered built-in ``MessageKey`` or custom string key.

        Returns:
            ``True`` only when neither this menu nor the application suppresses
            the message. This does not indicate whether it is currently shown.

        Raises:
            KeyError: If ``key`` is not registered in the application.
        """
        self.app._validate_message_key(key)
        return key not in self._disabled_messages and self.app._is_message_enabled(key)

    def _prepare_open(self) -> None:
        """Reset transient navigation state whenever this menu becomes visible."""
        if self._input is not None:
            self._input.buffer = ""
        self._focused_panel = None
        self._selected_index = 0
        self._choice_index = None
        self._normalize_selection()
        self._normalize_focus()
        self._hover_current(None)
        self._invalidate_renderer()

    def _initialize_runtime(self) -> None:
        """Create renderers and workers the first time this menu is opened."""
        self._running = True
        try:
            self._menu_renderer = MenuRenderer(self)
            self._terminal_renderer = TerminalRenderer(
                menu=self,
                menu_renderer=self._menu_renderer,
                content_spacing=self._content_spacing,
            )
            self._event_loop = self._create_event_loop()
        except BaseException:
            self._running = False
            self._event_loop = None
            self._menu_renderer = None
            self._terminal_renderer = None
            raise

    def stop(self) -> None:
        """Request Back/Quit, presenting choices while background work is active.

        A child returns to its parent, preserving the parent's selection, input
        buffer and preview without invoking hover callbacks, and keeps
        initialized workers running. At the root, include work from every
        initialized menu: exit immediately if none is active, otherwise offer
        Force quit, Wait and quit, and Cancel.
        Waiting suspends new refreshes while current work drains; Cancel restores
        navigation. Force quit restores terminal state then exits the process.
        This call requests navigation or shutdown and returns immediately.

        Call this on the visible menu from a UI callback. Calling it on a menu
        outside the current navigation stack stops the application directly.
        It does not join producer threads here; normal terminal teardown waits
        for them later. A producer that never returns requires cooperative
        cancellation or the process-level Force quit option.
        """
        at_root = len(self.app._menu_stack) <= 1 and (
            self in self.app._menu_stack or not self.app._menu_stack and self.is_main
        )
        if at_root:
            if self._current_exit_panels():
                self._begin_task_exit_choice()
            else:
                self._stop_immediately()
            return
        if self not in self.app._menu_stack:
            self._stop_immediately()
            return
        self.app.pop_menu()

    def _stop_immediately(self) -> None:
        self._running = False
        self.app._running = False

    def _position_of(self, command: MenuCommand) -> int:
        self._require_command(command)
        return self._commands.index(command)

    def _require_command(self, command: MenuCommand) -> None:
        if (
            not isinstance(command, MenuCommand)
            or command._menu is not self
            or command not in self._commands
        ):
            raise ValueError("Menu command does not belong to this menu")

    def _position_of_content_panel(self, panel: ContentPanel) -> int:
        self._require_content_panel(panel)
        return self._content_panels.index(panel)

    def _require_content_panel(self, panel: ContentPanel) -> None:
        if (
            not isinstance(panel, ContentPanel)
            or panel._menu is not self
            or panel._removed
            or panel not in self._content_panels
        ):
            raise ValueError("Content panel does not belong to this menu")

    def _validate_content_position(
        self,
        position: int | None,
        *,
        allow_end: bool,
    ) -> int:
        if position is None:
            return len(self._content_panels)
        if isinstance(position, bool) or not isinstance(position, int):
            raise TypeError("Content panel position must be an integer or None")
        upper = (
            len(self._content_panels) if allow_end else len(self._content_panels) - 1
        )
        if position < 0 or position > upper:
            raise ValueError("Content panel position is outside the menu")
        return position

    @staticmethod
    def _validate_auto_scroll(mode: AutoScrollMode | None) -> None:
        if mode not in (None, "smart", "strict"):
            raise ValueError("auto_scroll must be 'smart', 'strict', or None")

    def _validate_position(self, position: int | None, *, allow_end: bool) -> int:
        if position is None:
            return len(self._commands)
        if isinstance(position, bool) or not isinstance(position, int):
            raise TypeError("Command position must be an integer or None")
        upper = len(self._commands) if allow_end else len(self._commands) - 1
        if position < 0 or position > upper:
            raise ValueError("Command position is outside the menu")
        return position

    def _selectable_indices(self) -> list[int]:
        return [
            index for index, command in enumerate(self._commands) if command.enabled
        ] + [len(self._commands)]

    def _normalize_selection(self) -> None:
        selectable = self._selectable_indices()
        if self._selected_index not in selectable:
            self._selected_index = selectable[0]
            self._choice_index = None

    def _move_selection(self, delta: int, binding: KeyBinding | None = None) -> None:
        selectable = self._selectable_indices()
        current = selectable.index(self._selected_index)
        self._selected_index = selectable[(current + delta) % len(selectable)]
        self._choice_index = None
        self._hover_current(binding)

    def _active_choice(self) -> MenuChoice | None:
        if self._selected_index >= len(self._commands):
            return None
        command = self._commands[self._selected_index]
        return command if isinstance(command, MenuChoice) else None

    def _choice_lines(self, choice: MenuChoice) -> tuple[ChoiceLine, ...]:
        renderer = self._menu_renderer or MenuRenderer(self)
        renderer.update()
        width = renderer.effective_width(get_terminal_size().columns - 2)
        return choice_lines(choice, width)

    def _hover_current(self, binding: KeyBinding | None) -> None:
        choice = self._active_choice()
        if choice is not None and self._choice_index is not None:
            option = choice.options[self._choice_index]
            if option.on_hover is not None:
                option.on_hover(
                    ChoiceContext(
                        self.app, self, choice, option, self._choice_index, binding
                    )
                )
            return
        if self._selected_index < len(self._commands):
            command = self._commands[self._selected_index]
            if command._on_hover is not None:
                command._on_hover(CommandContext(self.app, self, command, binding))

    def _move_choice_horizontal(self, delta: int, binding: KeyBinding) -> None:
        choice = self._active_choice()
        if choice is None:
            return
        ordered = [
            index for line in self._choice_lines(choice) for index in line.indices
        ]
        if self._choice_index is None:
            if delta < 0:
                return
            self._choice_index = ordered[0]
        elif self._choice_index == ordered[0] and delta < 0:
            self._choice_index = None
        else:
            candidate = ordered.index(self._choice_index) + delta
            if not 0 <= candidate < len(ordered):
                return
            self._choice_index = ordered[candidate]
        self._hover_current(binding)

    def _move_choice_vertical(self, delta: int, binding: KeyBinding) -> bool:
        choice = self._active_choice()
        if choice is None or self._choice_index is None:
            return False
        lines = self._choice_lines(choice)
        current_row = next(
            row for row, line in enumerate(lines) if self._choice_index in line.indices
        )
        target_row = current_row + delta
        if target_row < 0:
            self._choice_index = None
            self._hover_current(binding)
        elif target_row >= len(lines):
            self._move_selection(1, binding)
        else:
            current_line = lines[current_row]
            x = current_line.starts[current_line.indices.index(self._choice_index)]
            target = lines[target_row]
            self._choice_index = min(
                target.indices,
                key=lambda index: abs(target.starts[target.indices.index(index)] - x),
            )
            self._hover_current(binding)
        return True

    def _has_content(self) -> bool:
        """Return whether the content box currently has a source."""
        return bool(self._content_panels) or self._output_task_session is not None

    def _visible_content_panels(self) -> tuple[ContentPanel, ...]:
        """Return panels currently projected into the terminal frame."""
        if self._task_exit is not None:
            return self._current_exit_panels()
        return self.content_panels

    def _visible_panel_description(self, panel: ContentPanel) -> str:
        view = self._task_exit
        if view is None or view.mode != "waiting" or view.wait_phase < 1:
            return panel.description
        return f"{panel.description}{'.' * view.wait_phase}"

    def _normalize_focus(self) -> None:
        panels = self._visible_content_panels()
        if self._focused_panel not in panels:
            self._focused_panel = None
        if not self._menu_box_visible and self._focused_panel is None and panels:
            self._focused_panel = panels[0]

    def _cycle_focus(self) -> None:
        focusable: list[ContentPanel | None] = [
            *([None] if self._menu_box_visible else []),
            *self._visible_content_panels(),
        ]
        if not focusable:
            return
        try:
            current = focusable.index(self._focused_panel)
        except ValueError:
            current = 0
        self._focused_panel = focusable[(current + 1) % len(focusable)]

    def _create_event_loop(self) -> EventLoop:
        if (
            self.app._input_handler is None
            or self._menu_renderer is None
            or self._terminal_renderer is None
        ):
            raise RuntimeError("Cannot create event loop before menu resources")
        return EventLoop(
            menu=self,
            input_handler=self.app._input_handler,
            menu_renderer=self._menu_renderer,
            terminal_renderer=self._terminal_renderer,
        )

    def _handle_event(self, event: InputEvent) -> None:
        binding = event.binding
        if self._task_exit is not None:
            self._handle_task_exit_event(event)
            return
        if not self._menu_box_visible:
            self._handle_hidden_menu_event(event)
            return
        if self._input is not None and self._alert is None:
            self._handle_input_event(event)
            return
        if binding is None:
            if event.text:
                self._show_automatic_message(
                    MessageKey.UNKNOWN_COMMAND, command=event.text
                )
            return
        if self.app._handle_global_command(binding, self):
            self._render_after_menu_event()
            return
        action = self.app.keymap.action_for(binding)
        if self._alert is not None:
            if action == "activate" and self._alert.on_confirm is not None:
                self._alert.on_confirm(CommandContext(self.app, self, None, binding))
                self.clear_alert()
            elif action == "back":
                self.stop()
            return
        if action == "focus" and self._has_content():
            self._cycle_focus()
        elif action == "back":
            self.stop()
        elif action is None and event.text:
            self._show_automatic_message(MessageKey.UNKNOWN_COMMAND, command=event.text)
        elif self._focused_panel is None:
            if action == "up":
                if not self._move_choice_vertical(-1, binding):
                    self._move_selection(-1, binding)
            elif action == "down":
                if not self._move_choice_vertical(1, binding):
                    self._move_selection(1, binding)
            elif action == "left":
                self._move_choice_horizontal(-1, binding)
            elif action == "right":
                self._move_choice_horizontal(1, binding)
            elif action == "activate":
                self._activate_selection(binding)
        elif action in {"up", "down", "left", "right"}:
            self._scroll_content(action)
        self._render_after_menu_event()

    def _render_after_menu_event(self) -> None:
        if self.presentation == "overlay":
            self._request_menu_render()
        else:
            self._invalidate_renderer()

    def _handle_hidden_menu_event(self, event: InputEvent) -> None:
        self._normalize_focus()
        binding = event.binding
        if binding is None:
            return
        if self.app._handle_global_command(binding, self):
            return
        action = self.app.keymap.action_for(binding)
        if action == "back":
            self.stop()
        elif action == "focus":
            self._cycle_focus()
        elif action in {"up", "down", "left", "right"}:
            self._scroll_content(action)
        # Focus and viewport offsets are already in the render key.

    def _handle_input_event(self, event: InputEvent) -> None:
        state = self._input
        if state is None:
            return
        binding = event.binding
        action = self.app.keymap.action_for(binding) if binding is not None else None
        if action == "activate":
            state.callback(state.buffer)
            return
        if action == "back":
            self.leave_input_mode()
            return
        if (
            binding is not None
            and binding.key == "backspace"
            and not any((binding.ctrl, binding.alt, binding.shift))
        ):
            graphemes = list(iter_graphemes(state.buffer))
            state.buffer = "".join(graphemes[:-1])
            return
        if event.text:
            state.buffer += event.text

    def _activate_selection(self, binding: KeyBinding) -> None:
        if self._selected_index == len(self._commands):
            self.stop()
            return
        command = self._commands[self._selected_index]
        if not command.enabled:
            return
        if isinstance(command, MenuChoice):
            if self._choice_index is None:
                self._choice_index = command.selected_index
                self._hover_current(binding)
            else:
                index = self._choice_index
                self.set_choice_index(command, index)
                command._on_select(
                    ChoiceContext(
                        self.app, self, command, command.options[index], index, binding
                    )
                )
            return
        command.callback(CommandContext(self.app, self, command, binding))

    def _scroll_content(
        self, direction: Literal["up", "down", "left", "right"]
    ) -> None:
        renderer = self._terminal_renderer
        panel = self._focused_panel
        if renderer is None or panel is None:
            return
        renderer.scroll_panel(panel, direction)

    def _display_input_buffer(self) -> str:
        state = self._input
        if state is None:
            return ""
        if not state.hidden:
            return state.buffer
        return "*" * len(list(iter_graphemes(state.buffer)))

    def _is_global_command_enabled(self, command: GlobalCommand) -> bool:
        return command not in self._disabled_global_commands

    def _global_callback(self, command: GlobalCommand) -> CommandCallback:
        return self._global_overrides.get(command, command.callback)

    def _detach_output_task(self, session: OutputTaskSession) -> None:
        if session is not self._output_task_session:
            return
        self._output_task_session = None
        panel = self._output_task_panel
        self._output_task_panel = None
        if panel is None or panel._removed:
            return
        if panel._runtime.renderer.rendered_content.finished:
            panel.remove()
        else:
            panel._runtime.remove_when_finished = True

    def _abandon_output_task(self, session: OutputTaskSession) -> None:
        if session is self._output_task_session:
            self._output_task_session = None
            panel = self._output_task_panel
            self._output_task_panel = None
            if panel is not None:
                panel._runtime.remove_when_finished = True

    def _show_automatic_message(self, key: str, **context: object) -> bool:
        if not self.is_message_enabled(key):
            return False
        message = self.app._get_message(key, **context)
        if message is None:
            return False
        self.display_state._set_registered_message(key, message)
        return True

    def _begin_task_exit_choice(self) -> None:
        if self._task_exit is not None:
            return
        panels = self._current_exit_panels()
        if not panels:
            self._stop_immediately()
            return
        self._task_exit = TaskExitState(
            mode="choice",
            selected_index=0,
            previous_focus=self._focused_panel,
            previous_selected_index=self._selected_index,
            wait_started_at=monotonic(),
            visible_panels=panels,
        )
        self._focused_panel = None
        self._invalidate_renderer()

    def _handle_task_exit_event(self, event: InputEvent) -> None:
        view = self._task_exit
        if view is None:
            return
        binding = event.binding
        action = self.app.keymap.action_for(binding) if binding is not None else None
        if action == "focus" and self._visible_content_panels():
            self._cycle_focus()
        elif action == "back":
            self._cancel_task_exit()
        elif self._focused_panel is not None:
            if action in {"up", "down", "left", "right"}:
                self._scroll_content(action)
        elif action == "up":
            view.move(-1)
        elif action == "down":
            view.move(1)
        elif action == "activate" and view.actions:
            self._activate_task_exit_action(view.actions[view.selected_index])
        self._invalidate_renderer()

    def _activate_task_exit_action(self, action: TaskExitAction) -> None:
        view = self._task_exit
        if view is None:
            return
        if action is TaskExitAction.CANCEL:
            self._cancel_task_exit()
            return
        if action is TaskExitAction.WAIT_AND_QUIT:
            view.mode = "waiting"
            view.selected_index = 0
            view.wait_started_at = monotonic()
            view.wait_phase = -1
            return
        if action is TaskExitAction.FORCE_QUIT:
            self._hard_exit_requested = True
            self._task_exit = None
            self._stop_immediately()

    def _cancel_task_exit(self) -> None:
        view = self._task_exit
        if view is None:
            return
        self._task_exit = None
        self._selected_index = view.previous_selected_index
        self._focused_panel = view.previous_focus
        self._normalize_selection()
        self._normalize_focus()
        self._invalidate_renderer()

    def _tick_task_exit(self, now: float) -> bool:
        view = self._task_exit
        if view is None:
            return False
        if self.app._menu_stack and self.app._menu_stack[-1] is not self:
            self._cancel_task_exit()
            return True
        active = self._current_exit_panels()
        changed = active != view.visible_panels
        view.visible_panels = active
        if not active:
            self._task_exit = None
            self._stop_immediately()
            return True
        if view.mode != "waiting":
            return changed
        phase = int((now - view.wait_started_at) / 0.4) % 3 + 1
        if phase != view.wait_phase:
            view.wait_phase = phase
            changed = True
        return changed

    def _current_exit_panels(self) -> tuple[ContentPanel, ...]:
        """Return unique logical operations that currently block root exit."""
        panels: list[ContentPanel] = []
        menus = (
            self,
            *(menu for menu in self.app._initialized_menus if menu is not self),
        )
        for menu in menus:
            if menu._event_loop is not None:
                panels.extend(menu._event_loop.active_panels)
        registration = self.app._active_output_task
        if (
            registration is not None
            and registration.panel is not None
            and registration.session.is_alive()
        ):
            panels.append(registration.panel)
        return tuple(dict.fromkeys(panels))

    def _invalidate_renderer(self) -> None:
        if self._terminal_renderer is not None:
            self._terminal_renderer.invalidate()
