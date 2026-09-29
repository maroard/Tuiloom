"""Define callback contracts, immutable contexts, and stable command handles.

Tuiloom invokes callbacks synchronously on the UI thread while dispatching
keyboard input or opening a menu. Keep them short and non-blocking; their return
values are ignored and their exceptions propagate through the application loop.
Calling an exposed callback directly runs it on the caller's thread instead.

Attributes:
    CommandCallback: Callable ``callback(context: CommandContext) -> None`` used
        for command activation, command-label keyboard hover, and alert
        confirmation. Hover means selection arrival, including initial menu
        opening with ``binding=None``; it is not a mouse event.
    InputCallback: Callable ``callback(text: str) -> None`` receiving the complete
        Unicode input buffer when the activation key submits it. Submission does
        not automatically leave input mode; the callback can call
        ``menu.leave_input_mode()`` on its captured menu.
    ChoiceCallback: Callable ``callback(context: ChoiceContext) -> None`` used
        for option preview and confirmed selection. Preview leaves the committed
        index unchanged; confirmation updates it before invoking the callback.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tuiloom.animation import TextSource
from tuiloom.key_binding import KeyBinding

if TYPE_CHECKING:
    from tuiloom.terminal_app import TerminalApp
    from tuiloom.terminal_menu import TerminalMenu


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Carry immutable metadata for one command callback invocation.

    Tuiloom supplies this context to activation and command-label hover
    callbacks on the UI thread, and to alert confirmation callbacks. Its fields
    are read-only references to live objects, not copies of application state.
    Constructing a context neither validates ownership nor executes a callback.
    Every field is required at construction, including the nullable fields.

    Attributes:
        app: Read-only ``TerminalApp`` reference to the dispatching application.
        menu: Read-only ``TerminalMenu`` reference to the menu receiving the
            event, including for a global command.
        command: Read-only registered ``MenuCommand`` or ``GlobalCommand``
            handle, or ``None`` for alert confirmation; has no default.
        binding: Read-only ``KeyBinding`` that caused the invocation, or ``None``
            for initial menu hover or programmatic execution; has no default.
    """

    app: TerminalApp
    menu: TerminalMenu
    command: MenuCommand | GlobalCommand | None
    binding: KeyBinding | None


type CommandCallback = Callable[[CommandContext], None]
"""Callable taking one CommandContext; UI dispatch ignores its return value."""

type InputCallback = Callable[[str], None]
"""Callable taking the submitted Unicode buffer without leaving input mode."""


@dataclass(frozen=True, slots=True)
class ChoiceContext:
    """Carry immutable metadata for an option preview or confirmed selection.

    Tuiloom invokes option callbacks with this context on the UI thread. During
    ``on_hover``, ``option`` and ``index`` describe the keyboard preview and can
    differ from the choice's committed ``selected_option`` and ``selected_index``.
    During ``on_select``, the selection has already been committed. Fields are
    read-only references to live objects; construction does not validate their
    consistency or execute a callback. Every field is required at construction,
    including nullable ``binding``.

    Attributes:
        app: Read-only ``TerminalApp`` reference to the invoking application.
        menu: Read-only ``TerminalMenu`` reference to the choice's owning menu.
        command: Read-only stable ``MenuChoice`` handle being previewed or
            confirmed.
        option: Read-only ``ChoiceOption`` being previewed or confirmed.
        index: Read-only ``int`` giving the zero-based index of ``option`` in
            ``command.options``, the original option tuple.
        binding: Read-only triggering ``KeyBinding``, or ``None`` for
            programmatic execution; has no default.
    """

    app: TerminalApp
    menu: TerminalMenu
    command: MenuChoice
    option: ChoiceOption
    index: int
    binding: KeyBinding | None


type ChoiceCallback = Callable[[ChoiceContext], None]
"""Callable taking one ChoiceContext for keyboard preview or committed choice."""


@dataclass(frozen=True, slots=True)
class ChoiceOption:
    """Describe an immutable option and its optional keyboard preview behavior.

    Pass options to ``TerminalMenu.add_choice()`` to validate their logical rows and
    registered message keys; this value object's constructor stores them without
    validation. Option previews do not change the committed choice.
    Construction requires ``label``; the remaining fields are keyword-only.

    Attributes:
        label: Read-only ``str`` displayed for the option; has no default and
            does not represent a separate application value.
        row: Read-only ``int`` giving the zero-based logical row in the expanded
            choice. Defaults to ``0``; must be in ``0..rows-1`` when registered
            with a menu. Rendering can wrap a logical row to fit the width.
        on_hover: Read-only callable ``callback(context: ChoiceContext) -> None``,
            or ``None`` by default. Tuiloom calls it synchronously on the UI
            thread when keyboard selection reaches the option, before
            confirmation; returns are ignored and exceptions propagate through
            the application loop.
        hover_message: Read-only ``str`` registered application message key for
            a temporary footer preview, or ``None`` by default. The preview
            obeys global message enablement and leaves persistent footer text
            and its registered identity unchanged.
    """

    label: TextSource
    row: int = field(default=0, kw_only=True)
    on_hover: ChoiceCallback | None = field(default=None, kw_only=True)
    hover_message: str | None = field(default=None, kw_only=True)


class MenuCommand:
    """Expose read-only metadata for one selectable menu command.

    Obtain registered handles with ``TerminalMenu.add_command()`` or
    ``add_submenu()``. Direct construction stores metadata without registering
    it. Use the owning menu's methods to rename, replace a callback, move,
    enable, disable, or remove a command. Its identity survives those changes;
    removal invalidates operations requiring membership, including ``position``.

    Attributes:
        label: Read-only current label; change with ``menu.set_command_label()``.
        callback: Read-only current activation callback; replace with
            ``menu.set_command_callback()``. Calling it directly executes on the
            caller's thread without checking enabled state or menu membership.
        position: Read-only current zero-based index among user commands,
            excluding the automatic Back/Quit action.
        enabled: Read-only local enablement; change with the menu's
            ``enable_command()`` or ``disable_command()`` methods.
    """

    __slots__ = ("_menu", "_label", "_callback", "_enabled", "_on_hover")

    def __init__(
        self,
        menu: TerminalMenu,
        label: TextSource,
        callback: CommandCallback,
        on_hover: CommandCallback | None = None,
    ) -> None:
        """Store command metadata without registering or invoking the command.

        Use ``TerminalMenu.add_command()`` for a handle that the menu can select
        and mutate. A directly constructed handle has no valid ``position``
        until it belongs to the menu's registered command collection.

        Args:
            menu: Menu associated with the handle, retained by reference.
            label: Visible command text.
            callback: Callable ``callback(context: CommandContext) -> None`` on
                activation; UI dispatch is synchronous on the UI thread, ignores
                returns, and propagates errors through the application loop.
            on_hover: Optional callable with the same signature when keyboard
                selection reaches the command. Defaults to ``None``; initial
                opening invokes it with ``binding=None`` before the menu's first
                runtime initialization, so it cannot start an output task yet.
                Neither callback runs in this constructor.

        Raises:
            TypeError: If ``callback`` is not callable, or ``on_hover`` is neither
                callable nor ``None``.
        """
        self._menu = menu
        self._label = label
        if not callable(callback):
            raise TypeError("callback must be callable")
        if on_hover is not None and not callable(on_hover):
            raise TypeError("on_hover must be callable or None")
        self._callback = callback
        self._enabled = True
        self._on_hover = on_hover

    @property
    def label(self) -> TextSource:
        """Read the command's current visible text.

        Returns:
            The label stored on the handle. Replace it through the owning menu's
            ``set_command_label()`` method.
        """
        return self._label

    @property
    def callback(self) -> CommandCallback:
        """Read the current activation callback without invoking it.

        Returns:
            The callable accepting ``CommandContext``. UI activation runs it on
            the UI thread; direct invocation uses the caller's thread and bypasses
            enabled-state checks. For ordinary commands, replace it with
            ``menu.set_command_callback()``.
            On a ``MenuChoice``, this is an adapter that invokes ``on_select``
            with ``ChoiceContext`` for the already committed option; it neither
            opens option navigation nor changes selection. Keyboard activation
            opens option navigation first and commits a preview on confirmation.
            Replace a choice's confirmation callback with
            ``menu.set_choice_callback()``.
        """
        return self._callback

    @property
    def position(self) -> int:
        """Locate the command in its owning menu's current user-command order.

        Returns:
            Zero-based index, excluding the automatic Back/Quit action. The
            value changes when commands are inserted, removed, or moved.

        Raises:
            ValueError: If the handle is not registered with its menu, including
                after removal or direct construction.
        """
        return self._menu._position_of(self)

    @property
    def enabled(self) -> bool:
        """Read whether menu navigation may select and activate the command.

        Returns:
            The local enablement flag, initially ``True``. Use the owning menu's
            ``enable_command()`` or ``disable_command()`` to change it; direct
            calls to ``callback`` do not inspect this flag.
        """
        return self._enabled


class MenuChoice(MenuCommand):
    """Expose a stable choice handle with separate preview and committed state.

    Obtain a registered, validated choice through ``TerminalMenu.add_choice()``.
    Keyboard navigation can preview an option without changing ``selected_index``;
    confirmation commits the option before calling ``on_select``. Activating the
    choice label first opens option navigation. The exposed ``callback`` instead
    adapts a direct ``CommandContext`` call to ``on_select(ChoiceContext)`` for
    the already committed option, without opening or changing the choice.

    Attributes:
        label: Read-only current choice label; change with
            ``menu.set_command_label()``.
        callback: Read-only activation adapter accepting ``CommandContext`` and
            invoking ``on_select`` for the committed option. Direct calls run on
            the caller's thread and bypass navigation and enabled-state checks.
            Calling it before confirmation raises ``RuntimeError``.
        position: Read-only current index among user commands, excluding
            Back/Quit; accessing it after removal raises ``ValueError``.
        enabled: Read-only local enablement, changed through the menu's
            ``enable_command()`` and ``disable_command()`` methods.
        options: Read-only immutable option tuple in its original index order.
        rows: Read-only number of logical option rows. In vertical mode, this
            equals the number of options.
        vertical: Read-only flag placing each option on its own logical row.
        selected_index: Read-only committed index, or ``None`` before the first
            confirmation; independent of keyboard preview. Change with
            ``menu.set_choice_index()`` without callbacks.
        on_select: Read-only confirmation callback; replace with
            ``menu.set_choice_callback()``.
        selected_option: Read-only option at the committed index, or ``None``.
        selected_label: Read-only fallback label of the committed option, or
            ``None``.
    """

    __slots__ = ("_options", "_rows", "_vertical", "_selected_index", "_on_select")

    def __init__(
        self,
        menu: TerminalMenu,
        label: TextSource,
        options: tuple[ChoiceOption, ...],
        rows: int,
        selected_index: int | None,
        on_select: ChoiceCallback,
        on_hover: CommandCallback | None,
        vertical: bool = False,
    ) -> None:
        """Store a choice's metadata without registration or selection callbacks.

        Prefer ``TerminalMenu.add_choice()``: it validates options, rows, indices,
        and registered preview messages before constructing this handle. This
        constructor validates callbacks and stores all other arguments directly.

        Args:
            menu: Associated menu, retained by reference.
            label: Visible selector text.
            options: Ordered tuple of ``ChoiceOption`` objects, retained without
                a copy. Must be nonempty for a usable choice; ``add_choice()``
                validates options and hover message keys, while this constructor
                stores them without validation.
            rows: Positive number of logical rows in the expanded choice;
                validated by ``add_choice()``, not by direct construction.
            vertical: Whether every option occupies its own logical row.
            selected_index: Initial committed zero-based index in ``options``,
                or ``None`` when no option is confirmed; validated by
                ``add_choice()``, not by direct construction.
            on_select: Callable ``callback(context: ChoiceContext) -> None`` on
                confirmation. UI dispatch is synchronous on the UI thread,
                ignores returns, and propagates exceptions through the
                application loop.
            on_hover: Callable ``callback(context: CommandContext) -> None`` when
                keyboard selection reaches the label, or ``None``. Required
                argument with no default; initial opening uses ``binding=None``
                before the menu's first runtime initialization. Neither callback
                is invoked here.

        Raises:
            TypeError: If ``on_select`` is not callable, or ``on_hover`` is neither
                callable nor ``None``.
        """
        if not callable(on_select):
            raise TypeError("on_select must be callable")
        super().__init__(menu, label, self._invoke_selection, on_hover)
        self._options = options
        self._rows = rows
        self._vertical = vertical
        self._selected_index = selected_index
        self._on_select = on_select

    @property
    def options(self) -> tuple[ChoiceOption, ...]:
        """Read the options in their original registration order.

        Returns:
            The immutable tuple of ``ChoiceOption`` objects retained by the
            handle, with indices starting at zero. Logical rows and visual
            wrapping can make keyboard traversal differ from this order.
        """
        return self._options

    @property
    def rows(self) -> int:
        """Read the logical row count of the expanded selector.

        Returns:
            The number of logical option rows. A logical row may wrap onto
            multiple visual rows to fit the current menu width.
        """
        return self._rows

    @property
    def vertical(self) -> bool:
        """Read whether options use one logical row each."""
        return self._vertical

    @property
    def selected_index(self) -> int | None:
        """Read the committed option index without inspecting keyboard preview.

        Returns:
            Zero-based index in ``options``, or ``None`` before confirmation.
            Keyboard confirmation and ``menu.set_choice_index()`` update this
            value; hover leaves it unchanged.
        """
        return self._selected_index

    @property
    def on_select(self) -> ChoiceCallback:
        """Read the confirmation callback without invoking it.

        Returns:
            The callable accepting ``ChoiceContext`` after keyboard confirmation
            has committed an option. Replace it with ``menu.set_choice_callback()``.
            Direct calls use the caller's thread and do not update selection.
        """
        return self._on_select

    @property
    def selected_option(self) -> ChoiceOption | None:
        """Read the committed option independently of the keyboard preview.

        Returns:
            The ``ChoiceOption`` at ``selected_index`` in the option tuple,
            or ``None`` before confirmation.

        Raises:
            IndexError: If direct construction supplied an out-of-range index
                or empty tuple. Registered choices validate these values.
        """
        if self._selected_index is None:
            return None
        return self._options[self._selected_index]

    @property
    def selected_label(self) -> str | None:
        """Read the fallback text of the committed option.

        Returns:
            ``selected_option.label`` as a plain string, or ``None`` before
            confirmation. This may differ from the hovered option's label while
            keyboard navigation is previewing another option. Animated labels
            render only inside the menu.

        Raises:
            IndexError: If direct construction supplied an out-of-range index
                or empty tuple. Registered choices validate these values.
        """
        option = self.selected_option
        return str(option.label) if option is not None else None

    def _invoke_selection(self, context: CommandContext) -> None:
        """Adapt command invocation to the currently validated choice option."""
        option = self.selected_option
        index = self.selected_index
        if option is None or index is None:
            raise RuntimeError(
                "Cannot invoke choice callback without a selected option"
            )
        self._on_select(
            ChoiceContext(
                self._menu.app,
                self._menu,
                self,
                option,
                index,
                context.binding,
            )
        )


class GlobalCommand:
    """Expose a stable handle for an invisible application-wide key command.

    Obtain registered handles with ``TerminalApp.add_global_command()`` so key
    type and collisions are checked. Direct construction only stores metadata
    and validates the callback. UI dispatch invokes a global command immediately
    with the menu receiving the key, subject to that menu's enablement and local
    callback override. The owning application's mutation methods update this
    handle without changing its identity.

    Attributes:
        binding: Read-only current key binding; change with
            ``app.set_global_command_binding()``.
        label: Read-only descriptive label; change with
            ``app.set_global_command_label()``.
        callback: Read-only application callback; replace with
            ``app.set_global_command_callback()``. This getter does not expose a
            menu's local override. Direct invocation uses the caller's thread and
            bypasses dispatch enablement checks and local overrides.
    """

    __slots__ = ("_app", "_binding", "_label", "_callback")

    def __init__(
        self,
        app: TerminalApp,
        binding: KeyBinding,
        label: str,
        callback: CommandCallback,
    ) -> None:
        """Store metadata without registering the global command or invoking it.

        Use ``TerminalApp.add_global_command()`` to validate binding types and
        collisions and make the command available for key dispatch.

        Args:
            app: Associated application, retained by reference.
            binding: Key binding that invokes the command when registered; this
                constructor stores it without validation.
            label: Descriptive text for a custom help display; global commands
                do not appear in the menu's selectable command list.
            callback: Callable ``callback(context: CommandContext) -> None`` on
                activation. UI dispatch is synchronous on the UI thread,
                ignores returns, and propagates errors through the application
                loop.

        Raises:
            TypeError: If ``callback`` is not callable.
        """
        self._app = app
        self._binding = binding
        self._label = label
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._callback = callback

    @property
    def binding(self) -> KeyBinding:
        """Read the current key binding for this global command.

        Returns:
            The stored binding. Change it atomically through
            ``app.set_global_command_binding()`` to validate collisions with
            system actions and other global commands.
        """
        return self._binding

    @property
    def label(self) -> str:
        """Read the descriptive label used by custom help displays.

        Returns:
            The stored label. Global commands remain absent from the selectable
            menu list; change this text with ``app.set_global_command_label()``.
        """
        return self._label

    @property
    def callback(self) -> CommandCallback:
        """Read the application callback independently of menu overrides.

        Returns:
            The callable accepting ``CommandContext``. Key dispatch may instead
            invoke the active menu's override. Direct invocation uses the caller's
            thread and bypasses overrides and enablement checks; replace the
            application callback with ``app.set_global_command_callback()``.
        """
        return self._callback
