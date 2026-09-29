from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from os import _exit
from queue import Empty, Queue
from sys import exception, stdout
from threading import current_thread, main_thread
from weakref import WeakValueDictionary

from tuiloom._message_registry import MessageRegistry
from tuiloom.cleanup import run_cleanup
from tuiloom.command import (
    CommandCallback,
    CommandContext,
    GlobalCommand,
)
from tuiloom.content_panel import ContentPanel
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.key_binding import KeyBinding, KeyMap
from tuiloom.output_capture import OutputCapture
from tuiloom.output_task import OutputTaskSession
from tuiloom.screen_content import ScreenContent
from tuiloom.terminal_menu import TerminalMenu


@dataclass(slots=True)
class _OutputTaskRegistration:
    """Associate a captured task with callbacks and exit state."""

    menu: TerminalMenu
    session: OutputTaskSession
    on_success: Callable[[object], None] | None
    on_error: Callable[[Exception], None] | None
    description: str
    panel: ContentPanel | None = None


class TerminalApp:
    """Own menus, shared commands and one interactive terminal application loop.

    Construct menus with this application, register a main menu or pass an entry
    to ``run()``, and call ``run()`` on Python's main thread. Configuration and
    navigation do not start another loop. During a run, mutate menus and this
    application from UI callbacks; content producers and output-task actions
    execute on workers and should not mutate UI state.

    Global content becomes an ordinary, independently mutable panel in each new
    menu. A shared configuration is reused without copying its source. In
    particular, one stream iterator can belong to only one panel in this
    application. A factory can supply independent configurations and sources:
    it is called once during each menu's construction, on that constructor's
    thread, and is not called when the menu is reopened. Its exceptions, invalid
    return type and repeated stream ownership fail the menu's construction.

    ``TerminalMenu.start_output_task()`` returns immediately with no task handle.
    One such task may be active across all menus. Its action runs in a non-daemon
    thread; Python stdout/stderr writes from all non-UI threads are captured
    while it runs, including unrelated workers. Subprocess output and direct
    file-descriptor writes are excluded. The action's result goes to
    ``on_success`` or its exception to ``on_error`` on the UI thread after the
    worker terminates. Non-``Exception`` failures are wrapped in ``RuntimeError``
    with their original cause. Callback return values are ignored; callback
    failures propagate through ``run()``. Shutdown discards pending callbacks
    and future captured output, but cannot interrupt the action itself.

    Attributes:
        name: Read-only application name displayed in menu boxes.
        global_content: Read-only reference to the shared ``ScreenContent``,
            or ``None``. Replacing or removing a menu's inherited panel does
            not change this reference or other menus' panels.
        global_content_factory: Read-only factory reference, or ``None``.
        keymap: Read-only reference to the owned, mutable ``KeyMap``. Its
            ``set_binding()`` rejects collisions with other system actions and
            global commands before changing a binding.
        global_commands: Immutable tuple snapshot of registered global-command
            handles. Handles expose current metadata; use this application's
            setters to update it. Commands are invisible unless you build a
            help display from their labels.
        main_menu: Read-only reference to the menu registered by
            ``set_main_menu()``, or ``None``; the visible menu may differ.
    """

    def __init__(
        self,
        name: str,
        global_content: ScreenContent | None = None,
        *,
        keymap: KeyMap | None = None,
        global_content_factory: Callable[[], ScreenContent] | None = None,
    ) -> None:
        """Create application-owned registries without starting terminal work.

        The supplied key map is retained and assigned one owner, rather than
        copied. Shared content is retained until each menu mounts it in a new
        panel; the factory is not invoked by this constructor. Each menu calls
        it once on its constructing thread and validates its returned content.
        Reusing a stream iterator in multiple panels of this application is
        rejected when the later panel is mounted, so factories should create
        independent iterators and any producer state that needs isolation.

        Args:
            name: Required string name displayed in every menu box.
            global_content: Shared ``ScreenContent`` used as the initial panel
                of each new menu, or ``None`` (the default) to omit that panel.
                Each panel owns its display state, but its source is not copied.
                Static content may be reused; mutable producer state stays
                shared unless a factory creates independent sources.
            keymap: ``KeyMap`` owned and mutated by this application, or
                ``None`` (the default) for a new map using Tab, arrows, Enter
                and Escape. One map has one application owner; use
                ``keymap.copy()`` for another application. Later mutations of
                the supplied map affect this application.
            global_content_factory: Zero-argument callable returning one
                ``ScreenContent`` per new menu, or ``None`` (the default).
                Mutually exclusive with ``global_content``; factory failures
                propagate from menu construction, not from this constructor.

        Raises:
            TypeError: If ``global_content`` is not ``ScreenContent`` or
                ``None``, or ``global_content_factory`` is not callable or
                ``None``.
            ValueError: If both content options are supplied, or ``keymap``
                already belongs to an application.
        """
        self._name = name
        if global_content is not None and not isinstance(global_content, ScreenContent):
            raise TypeError("global_content must be a ScreenContent or None")
        if global_content is not None and global_content_factory is not None:
            raise ValueError("Use global_content or global_content_factory, not both")
        if global_content_factory is not None and not callable(global_content_factory):
            raise TypeError("global_content_factory must be callable or None")
        self._global_content = global_content
        self._global_content_factory = global_content_factory
        self._stream_owners: WeakValueDictionary[int, ContentPanel] = (
            WeakValueDictionary()
        )
        self._keymap = keymap if keymap is not None else KeyMap()
        self._keymap._set_external_validator(self._validate_system_binding)
        self._global_commands: list[GlobalCommand] = []
        self._main_menu: TerminalMenu | None = None
        self._message_registry = MessageRegistry()
        self._output_capture = OutputCapture()
        self._active_output_task: _OutputTaskRegistration | None = None
        self._output_task_outcomes: Queue[_OutputTaskRegistration] = Queue()
        self._input_handler: InputHandler | None = None
        self._menu_stack: list[TerminalMenu] = []
        self._initialized_menus: list[TerminalMenu] = []
        self._running = False

    @property
    def name(self) -> str:
        """Inspect the name displayed in every menu box.

        Returns:
            The original application name. This property is read-only.
        """
        return self._name

    @property
    def global_content(self) -> ScreenContent | None:
        """Inspect the shared initial content configuration for new menus.

        Each menu receives its own ordinary panel around this same source;
        replacing or removing that panel affects only that menu. Stream
        iterators cannot be shared between panels in the same application.

        Returns:
            The original ``ScreenContent`` reference, or ``None`` when no shared
            configuration was supplied, including when a factory is used. This
            property is read-only and does not expose a menu's current panels.
        """
        return self._global_content

    @property
    def global_content_factory(self) -> Callable[[], ScreenContent] | None:
        """Inspect the factory used to provide each new menu's initial content.

        Reading this property does not invoke the factory. Menu construction
        invokes it once on the caller's thread, validates ``ScreenContent`` and
        mounts the result. Reopening a menu does not invoke it again. A factory
        must create independent sources to isolate iterator or producer state.

        Returns:
            The original zero-argument factory, or ``None`` when unused. The
            reference is read-only; no wrapper or copy is returned.
        """
        return self._global_content_factory

    def _create_global_content(self) -> ScreenContent | None:
        if self._global_content_factory is None:
            return self._global_content
        content = self._global_content_factory()
        if not isinstance(content, ScreenContent):
            raise TypeError("global_content_factory must return a ScreenContent")
        return content

    def _claim_stream(self, content: ScreenContent, panel: ContentPanel) -> None:
        if content._kind != "stream":
            return
        stream = content._stream()
        owner = self._stream_owners.get(id(stream))
        if owner is not None and owner is not panel:
            raise ValueError(
                "A stream can only be mounted by one panel per application"
            )
        self._stream_owners[id(stream)] = panel

    def _prune_stream_claims(self, panel: ContentPanel) -> None:
        """Retain claims only for mounted, queued and retiring stream sources."""
        sources = (panel._content, panel._runtime.pending_content)
        retained = {
            id(content._stream())
            for content in sources
            if content is not None and content._kind == "stream"
        }
        for identity, owner in tuple(self._stream_owners.items()):
            if owner is panel and identity not in retained:
                del self._stream_owners[identity]

    def _release_stream_claims(self, panel: ContentPanel) -> None:
        """Release a removed panel's claims after its worker has terminated."""
        for identity, owner in tuple(self._stream_owners.items()):
            if owner is panel:
                del self._stream_owners[identity]

    @property
    def keymap(self) -> KeyMap:
        """Access the mutable system bindings owned by this application.

        ``set_binding()`` validates the action, binding type and collisions
        with other system actions or global commands before applying a change.
        During a run, change bindings from UI callbacks; subsequent input uses
        the new map. Use ``copy()`` before supplying its settings to another app.

        Returns:
            The original owned ``KeyMap``, not a copy. This property's reference
            is read-only, while the map's bindings are configurable.
        """
        return self._keymap

    @property
    def global_commands(self) -> tuple[GlobalCommand, ...]:
        """Inspect registered global commands in registration order.

        Commands do not add visible menu rows. Their handles expose current
        binding, label and callback metadata; use the application's setters to
        change these values.

        Returns:
            An immutable tuple snapshot of the registered handles. Adding a
            command later does not change an existing tuple, but its handles
            continue to reflect metadata updates.
        """
        return tuple(self._global_commands)

    @property
    def main_menu(self) -> TerminalMenu | None:
        """Inspect the menu used by ``run()`` when no entry is supplied.

        Main-menu registration does not identify the currently visible menu or
        necessarily the root of a run started with an explicit entry.

        Returns:
            The menu registered by ``set_main_menu()``, or ``None`` before
            registration. This property is read-only.
        """
        return self._main_menu

    def set_main_menu(self, menu: TerminalMenu) -> None:
        """Choose the application-owned default entry for future ``run()`` calls.

        Registration changes immediately without opening a menu or moving the
        navigation stack. Unless explicitly configured, this menu's exit label
        becomes ``"Quit"`` and a replaced main menu's becomes ``"Back"``.
        Navigation subsequently derives automatic labels from stack position.
        Calling this with the already registered menu is harmless.

        Args:
            menu: ``TerminalMenu`` owned by this application.

        Raises:
            ValueError: If ``menu`` belongs to another application.
        """
        if menu.app is not self:
            raise ValueError("Main menu must belong to this TerminalApp")
        previous = self._main_menu
        if previous is not None and previous is not menu:
            if not previous._exit_label_explicit:
                previous._exit_label = "Back"
        self._main_menu = menu
        if not menu._exit_label_explicit:
            menu._exit_label = "Quit"

    def push_menu(self, menu: TerminalMenu) -> None:
        """Open an owned menu above the current one in the existing loop.

        The stack changes immediately. Selection resets to the first selectable
        row, focus resets to the menu box or an available panel, choice preview
        is cleared and an existing input session's buffer is emptied. Commands,
        panels, alerts and the input session itself are preserved. An inherited
        presentation resolves from the current parent, or to inline at a root.
        Automatic exit labels become Quit at the root and Back below it.

        Initial ``on_hover`` runs synchronously on the caller's thread, after
        the stack changes; its failure does not roll back navigation. During a
        run, call this from a UI callback. First-open workers start lazily when
        the loop next services the menu; existing runtimes are reused. Covered
        menus keep their workers and continue processing content without input
        or rendering. Calling this before ``run()`` starts no terminal work;
        ``run()`` creates its own stack from its entry menu.

        Args:
            menu: Owned ``TerminalMenu`` that is not already in this stack.

        Raises:
            ValueError: If ``menu`` is not a menu owned by this application or
                is already in the stack. Validation leaves navigation unchanged.
            Exception: If an initial ``on_hover`` callback fails. Its original
                exception propagates after navigation has changed.
        """
        self._validate_navigation_menu(menu)
        menu._resolve_presentation(self._menu_stack[-1] if self._menu_stack else None)
        self._menu_stack.append(menu)
        self._sync_exit_labels()
        menu._prepare_open()

    def pop_menu(self) -> None:
        """Return to the previous menu, or request application shutdown at a root.

        With multiple entries, remove the top immediately and invalidate the
        parent's frame without resetting its selection, focus, input buffer or
        choice preview and without invoking ``on_hover``. The removed menu's
        initialized workers remain alive until application shutdown. During a
        run, call this from a UI callback; the parent renders on a later loop
        turn and automatic exit labels follow the remaining stack positions.

        At one entry, delegate to that menu's ``stop()``: active background work
        can present Force quit, Wait and quit, and Cancel choices instead of
        stopping immediately. With an empty stack, request shutdown directly.
        This call does not join workers or restore terminal state itself.
        """
        if len(self._menu_stack) <= 1:
            if self._menu_stack:
                self._menu_stack[-1].stop()
            else:
                self._running = False
            return
        self._menu_stack.pop()
        self._sync_exit_labels()
        self._menu_stack[-1]._invalidate_renderer()

    def replace_menu(self, menu: TerminalMenu) -> None:
        """Replace the visible menu, or open the first menu in an empty stack.

        This changes the stack immediately without creating another loop. The
        target may be the current top, but cannot appear elsewhere in the stack.
        Selection, focus and choice preview reset, and an existing input
        session's buffer is emptied; commands, panels, alerts and the session
        itself survive. Replacing with the current top preserves its resolved
        presentation; a different target inherits from the replaced menu, or
        resolves to inline if the stack was empty. Automatic exit labels follow
        the new stack positions unless explicitly configured.

        Initial ``on_hover`` executes on the caller's thread after replacement;
        a callback failure does not roll back the stack. During a run, invoke
        this from a UI callback. New runtime work starts lazily on a later loop
        turn; existing runtime work is reused. An initialized replaced menu
        remains serviced without input or rendering until shutdown. Before
        ``run()``, this starts no terminal work and that run resets the stack.

        Args:
            menu: ``TerminalMenu`` owned by this application; the current top
                is permitted as a target for reopening.

        Raises:
            ValueError: If ``menu`` is not an owned menu or appears below the
                current top. Validation leaves navigation unchanged.
            Exception: If an initial ``on_hover`` callback fails. Its original
                exception propagates after replacement.
        """
        self._validate_navigation_menu(menu, allow_current_top=True)
        if not self._menu_stack or self._menu_stack[-1] is not menu:
            menu._resolve_presentation(
                self._menu_stack[-1] if self._menu_stack else None
            )
        if not self._menu_stack:
            self._menu_stack.append(menu)
        else:
            self._menu_stack[-1] = menu
        self._sync_exit_labels()
        menu._prepare_open()

    def reset_to(self, menu: TerminalMenu) -> None:
        """Return to an owned stack entry, or make an owned menu the sole root.

        If the target is already stacked, remove all entries above it and keep
        its resolved presentation. Otherwise replace the whole stack and resolve
        inherited presentation to inline. Selection, focus and choice preview
        reset and an existing input buffer is emptied; commands, panels, alerts
        and the input session itself survive. Automatic exit labels follow the
        resulting stack positions unless explicitly configured.

        Navigation occurs immediately and initial ``on_hover`` runs on the
        caller's thread afterward; a callback failure does not restore the old
        stack. During a run, call this from a UI callback. First-open runtime
        work starts lazily on a later loop turn. Initialized menus removed from
        the stack retain their workers and are serviced without input or
        rendering until shutdown. Before ``run()``, no terminal work is started
        and that run resets the stack from its entry menu.

        Args:
            menu: ``TerminalMenu`` owned by this application, whether currently
                in the navigation stack or not.

        Raises:
            ValueError: If ``menu`` is not an owned menu. Validation leaves
                navigation unchanged.
            Exception: If an initial ``on_hover`` callback fails. Its original
                exception propagates after the stack has changed.
        """
        if not isinstance(menu, TerminalMenu) or menu.app is not self:
            raise ValueError("Menu must belong to this TerminalApp")
        if menu in self._menu_stack:
            del self._menu_stack[self._menu_stack.index(menu) + 1 :]
        else:
            menu._resolve_presentation(None)
            self._menu_stack[:] = [menu]
        self._sync_exit_labels()
        menu._prepare_open()

    def _sync_exit_labels(self) -> None:
        for index, menu in enumerate(self._menu_stack):
            if not menu._exit_label_explicit:
                menu._exit_label = "Quit" if index == 0 else "Back"

    def _validate_navigation_menu(
        self,
        menu: TerminalMenu,
        *,
        allow_current_top: bool = False,
    ) -> None:
        if not isinstance(menu, TerminalMenu) or menu.app is not self:
            raise ValueError("Menu must belong to this TerminalApp")
        if menu in self._menu_stack and not (
            allow_current_top and self._menu_stack and self._menu_stack[-1] is menu
        ):
            raise ValueError("Menu is already present in the navigation stack")

    def add_global_command(
        self,
        binding: KeyBinding,
        label: str,
        callback: CommandCallback,
    ) -> GlobalCommand:
        """Register an application-wide keyboard command without a visible row.

        Registration is immediate and does not invoke the callback. When the
        binding is received, an enabled command executes on the UI thread with
        ``CommandContext`` identifying this app, the receiving menu, this handle
        and the binding. Callback return values are ignored; failures propagate
        through ``run()``. Each menu may disable the command or override its
        callback. A visible input session consumes its keys before global
        commands, while a hidden command box or an alert still permits them.

        Bindings compare as normalized ``KeyBinding`` values. A binding must
        not match any system action or another registered global command.
        Later ``keymap.set_binding()`` also rejects global-command collisions.
        During a run, register commands from UI callbacks.

        Args:
            binding: ``KeyBinding`` that invokes the command directly.
            label: Metadata label for user-built help displays. It does not
                create a menu row or an automatic help display.
            callback: Callable receiving one ``CommandContext`` when invoked.

        Returns:
            The registered ``GlobalCommand`` handle, owned by this application.
            Use application setters to change its binding, label or callback.

        Raises:
            TypeError: If ``callback`` is not callable or ``binding`` is not a
                ``KeyBinding``. No command is registered on failure.
            ValueError: If ``binding`` collides with any system action or
                another global command. No command is registered on failure.
        """
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._validate_global_binding(binding)
        command = GlobalCommand(self, binding, label, callback)
        self._global_commands.append(command)
        return command

    def set_global_command_binding(
        self, command: GlobalCommand, binding: KeyBinding
    ) -> None:
        """Replace an owned global command's keyboard binding after validation.

        The change is immediate and applies to subsequent input in all menus,
        including menus with local callback overrides or disablement. No
        callback is invoked. Reusing the command's current binding is allowed;
        matching another system action or global command is rejected before
        metadata changes. During a run, change bindings from UI callbacks.

        Args:
            command: ``GlobalCommand`` handle owned by this application.
            binding: New ``KeyBinding`` used to invoke this command.

        Raises:
            ValueError: If ``command`` is foreign or not a ``GlobalCommand``,
                or the binding belongs to a system action or another global
                command. The previous binding remains unchanged.
            TypeError: If ``binding`` is not a ``KeyBinding``.
        """
        self._require_global(command)
        self._validate_global_binding(binding, excluding=command)
        command._binding = binding

    def set_global_command_label(self, command: GlobalCommand, label: str) -> None:
        """Replace an owned global command's label immediately.

        The command is invisible to Tuiloom's menu rows; this label is metadata
        available to user-built help displays. No callback is invoked or frame
        requested by this method. During a run, update it from a UI callback.

        Args:
            command: ``GlobalCommand`` handle owned by this application.
            label: New metadata label; no formatting or validation is applied.

        Raises:
            ValueError: If ``command`` is not a ``GlobalCommand`` owned by this
                application. Its label is unchanged on failure.
        """
        self._require_global(command)
        command._label = label

    def set_global_command_callback(
        self, command: GlobalCommand, callback: CommandCallback
    ) -> None:
        """Replace the default behavior of an owned global command.

        This stores the callable immediately without invoking it. Subsequent
        dispatch uses it unless the receiving menu has a local override; local
        overrides and disablement are preserved. On dispatch the callable runs
        on the UI thread with ``CommandContext``, its return value is ignored
        and its exceptions propagate through ``run()``. During a run, call this
        setter from a UI callback.

        Args:
            command: ``GlobalCommand`` handle owned by this application.
            callback: New callable accepting the command's ``CommandContext``.

        Raises:
            ValueError: If ``command`` is not an owned ``GlobalCommand``.
            TypeError: If ``callback`` is not callable. The old callback is
                preserved on validation failure.
        """
        self._require_global(command)
        if not callable(callback):
            raise TypeError("callback must be callable")
        command._callback = callback

    def add_message(self, key: str, text: str) -> None:
        """Register static message text for menus to reference by a unique key.

        Registration is immediate but does not display the message or request
        a frame. A menu may use the key for a message or hover preview and may
        suppress it independently. This adds custom text; it cannot replace a
        built-in or previously registered message. During a run, register from
        a UI callback.

        Args:
            key: Nonempty custom string key, unique across built-in and custom
                messages in this application.
            text: Message text retained as supplied, without formatting.

        Raises:
            ValueError: If ``key`` is empty or already registered. The existing
                registry is unchanged on failure.
        """
        self._message_registry.add_message(key, text)

    def disable_message(self, key: str) -> None:
        """Suppress a registered message for all menus of this application.

        The global flag changes immediately and future resolutions return no
        text, even if a menu enables the key locally. Repeated disablement is
        harmless. This does not clear message text already stored in a menu's
        display state or request a frame. During a run, call from a UI callback.

        Args:
            key: Registered built-in ``MessageKey`` or custom string key.

        Raises:
            KeyError: If ``key`` is not registered. No flag changes on failure.
        """
        self._message_registry.disable(key)

    def enable_message(self, key: str) -> None:
        """Allow a registered message to be resolved at application level.

        The global flag changes immediately, while each menu's independent
        disablement is retained. Calling this for an already enabled key is
        harmless. It does not display text or request a frame; later message
        resolution determines whether to show it. During a run, call from a UI
        callback.

        Args:
            key: Registered built-in ``MessageKey`` or custom string key.

        Raises:
            KeyError: If ``key`` is not registered. No flag changes on failure.
        """
        self._message_registry.enable(key)

    def _require_global(self, command: GlobalCommand) -> None:
        if not isinstance(command, GlobalCommand) or command._app is not self:
            raise ValueError("Global command does not belong to this application")

    def _validate_global_binding(
        self,
        binding: KeyBinding,
        *,
        excluding: GlobalCommand | None = None,
    ) -> None:
        if not isinstance(binding, KeyBinding):
            raise TypeError("Global command bindings must be KeyBinding instances")
        action = self._keymap.action_for(binding)
        if action is not None:
            raise ValueError(
                f"Binding {binding!r} is reserved by system action {action!r}"
            )
        if any(
            command is not excluding and command.binding == binding
            for command in self._global_commands
        ):
            raise ValueError(f"Binding {binding!r} already invokes a global command")

    def _validate_system_binding(self, action: str, binding: KeyBinding) -> None:
        if any(command.binding == binding for command in self._global_commands):
            raise ValueError(
                f"Binding {binding!r} already invokes a global command; "
                f"cannot assign system action {action!r}"
            )

    def _get_message(self, key: str, **context: object) -> str | None:
        return self._message_registry.get(key, **context)

    def _validate_message_key(self, key: str) -> None:
        self._message_registry.validate_key(key)

    def _is_message_enabled(self, key: str) -> bool:
        return self._message_registry.is_enabled(key)

    def _handle_global_command(self, binding: KeyBinding, menu: TerminalMenu) -> bool:
        command = next(
            (
                candidate
                for candidate in self._global_commands
                if candidate.binding == binding
            ),
            None,
        )
        if command is None or not menu._is_global_command_enabled(command):
            return False
        behavior = menu._global_callback(command)
        behavior(
            CommandContext(
                app=self,
                menu=menu,
                command=command,
                binding=binding,
            )
        )
        return True

    def _start_output_task(
        self,
        menu: TerminalMenu,
        action: Callable[[], object],
        on_success: Callable[[object], None],
        on_error: Callable[[Exception], None],
        description: str,
    ) -> OutputTaskSession:
        if self._active_output_task is not None:
            raise RuntimeError("Another output task is already running")
        session = OutputTaskSession(description)
        registration = _OutputTaskRegistration(
            menu, session, on_success, on_error, description
        )
        self._active_output_task = registration
        try:
            session.start(
                action,
                self._output_capture,
                lambda completed: self._output_task_outcomes.put(registration),
            )
        except BaseException:
            self._active_output_task = None
            raise
        return session

    def _attach_output_panel(
        self,
        session: OutputTaskSession,
        panel: ContentPanel,
    ) -> None:
        registration = self._active_output_task
        if registration is None or registration.session is not session:
            raise RuntimeError("Output task registration is no longer active")
        registration.panel = panel

    def _dispatch_output_task_outcome(self) -> TerminalMenu | None:
        try:
            registration = self._output_task_outcomes.get_nowait()
        except Empty:
            return None
        if registration is not self._active_output_task:
            return None

        registration.session.join()
        self._active_output_task = None
        registration.menu._detach_output_task(registration.session)
        outcome = registration.session.outcome
        if outcome is None:
            raise RuntimeError("Completed output task has no outcome")

        if outcome.error is None:
            if registration.on_success is not None:
                registration.on_success(outcome.result)
        elif registration.on_error is not None:
            registration.on_error(outcome.error)
        return registration.menu

    def _shutdown_output_task(self, *, wait_for_worker: bool = True) -> None:
        """Abandon an active task, optionally waiting for its worker."""
        registration = self._active_output_task
        if registration is None:
            return
        registration.on_success = None
        registration.on_error = None
        self._active_output_task = None
        registration.session.cancel()
        registration.menu._abandon_output_task(registration.session)
        if wait_for_worker:
            registration.session.join()

    def run(self, entry_menu: TerminalMenu | None = None) -> None:
        """Block on the main thread until this terminal application's loop exits.

        Use an interactive terminal for input and ANSI screen control. Each run
        builds a fresh navigation stack from its entry, opens that menu and
        invokes its initial ``on_hover`` synchronously. Menu runtimes and source
        workers start lazily as the loop first services them. Input, rendering
        and command, hover, input and task-outcome callbacks run on this thread;
        content producers and output-task actions run on non-daemon workers.
        Initialized hidden or removed menus continue processing content without
        input or rendering until shutdown.

        The run owns terminal input mode, the alternate screen, cursor and
        focus-reporting state, and temporarily routes Python ``sys.stdout`` and
        ``sys.stderr``. During a captured output task, writes from all non-UI
        threads are collected, including unrelated workers; subprocess and
        direct file-descriptor output are excluded. The task API returns no
        handle. Its result or exception is delivered by one UI-thread outcome
        callback during normal operation, after its worker terminates. Callback
        failures propagate; pending callbacks are discarded during shutdown.

        Normal teardown discards future task output and joins the active task,
        then requests source cancellation and joins initialized panel workers
        before closing input and restoring the screen. Cancellation cannot
        interrupt a blocked iterator,
        producer or task action: a producer must return or provide a cooperative
        cancellation hook, and an output-task action must return on its own.
        A worker that never stops can therefore block this call and delay
        terminal restoration. Root exit controls offer Force quit to restore
        terminal state without joining workers and terminate the whole process
        with status 0; that path does not return or run normal Python process
        finalization.

        Once input initialization succeeds, every independent teardown action
        is attempted even if another raises, including screen restoration if
        screen entry was attempted. A lone failure propagates; multiple
        application and cleanup failures are preserved in an exception group.
        Routed Python streams are restored when capture leaves its context.

        Args:
            entry_menu: ``TerminalMenu`` owned by this application to use as
                root, or ``None`` (the default) to use ``main_menu``. An explicit
                entry need not be registered as main and does not change that
                registration. Previous manually built stacks are replaced.

        Returns:
            ``None`` after normal shutdown and terminal teardown. Force quit
            terminates the process and never returns.

        Raises:
            RuntimeError: If no entry or main menu exists, this is not Python's
                main thread, or this application's output capture is already
                installed, such as during a nested call to ``run()``.
            ValueError: If the chosen entry belongs to another application.
            BaseException: If terminal input/output, rendering, a content
                producer, a user callback or a cleanup action fails. Original
                failures propagate when no additional cleanup failure occurs.
            BaseExceptionGroup: If multiple application or cleanup failures
                need to be preserved. Groups may contain nested cleanup groups.
        """
        initial_menu = entry_menu if entry_menu is not None else self._main_menu
        if initial_menu is None:
            raise RuntimeError("Cannot run TerminalApp: no main menu has been set")
        if initial_menu.app is not self:
            raise ValueError("Entry menu must belong to this TerminalApp")
        if current_thread() is not main_thread():
            raise RuntimeError("TerminalApp.run() must execute on the main thread")

        with self._output_capture.install():
            self._input_handler = InputHandler()
            self._menu_stack = []
            self._initialized_menus = []
            self._running = True
            screen_attempted = False
            try:
                self.push_menu(initial_menu)
                screen_attempted = True
                self._enter_terminal_screen()
                self._run_application_loop()
            finally:
                self._running = False
                hard_exit_requested = any(
                    menu._hard_exit_requested
                    for menu in (*self._initialized_menus, *self._menu_stack)
                )
                actions: list[Callable[[], object]] = [
                    lambda: self._shutdown_output_task(
                        wait_for_worker=not hard_exit_requested
                    ),
                    lambda: self._shutdown_menu_runtimes(abandon=hard_exit_requested),
                    self._input_handler.close,
                ]
                if screen_attempted:
                    actions.append(self._leave_terminal_screen)
                try:
                    run_cleanup(
                        actions,
                        message="Application and cleanup failures",
                        prior_error=exception(),
                    )
                finally:
                    self._input_handler = None
                    if hard_exit_requested:
                        _exit(0)

    def _run_application_loop(self) -> None:
        """Drive initialized menu runtimes until navigation requests shutdown."""
        while self._running:
            top = self._menu_stack[-1]
            if top not in self._initialized_menus:
                top._initialize_runtime()
                self._initialized_menus.append(top)
            for menu in tuple(self._initialized_menus):
                if menu is top:
                    continue
                if menu._event_loop is not None:
                    menu._event_loop.run_once(
                        process_input=False,
                        render=False,
                        block=False,
                    )
                if not self._running:
                    break
            if not self._running:
                break
            top = self._menu_stack[-1]
            if top not in self._initialized_menus:
                continue
            if top._event_loop is None:
                raise RuntimeError("Initialized menu has no event loop")
            top._event_loop.run_once(
                process_input=True,
                render=True,
                block=True,
            )

    def _shutdown_menu_runtimes(self, *, abandon: bool = False) -> None:
        """Release every initialized runtime, joining workers on normal exit."""
        actions: list[Callable[[], object]] = []
        for menu in self._initialized_menus:
            loop = menu._event_loop
            if loop is None:
                continue
            actions.append(loop.abandon if abandon else loop.close)
            menu._event_loop = None
            menu._running = False
        run_cleanup(actions, message="Menu runtime cleanup failures")

    def _enter_terminal_screen(self) -> None:
        stdout.write("\033[?1049h\033[2J\033[H\033[?25l")
        stdout.write("\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1007l")
        stdout.write("\033[?1004s\033[?1004h")
        stdout.flush()

    def _leave_terminal_screen(self) -> None:
        # Disable first as a fallback for terminals lacking mode save/restore.
        stdout.write("\033[?1004l\033[?1004r")
        stdout.write("\033[?25h")
        stdout.write("\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1007l")
        stdout.write("\033[?1049l")
        stdout.flush()
