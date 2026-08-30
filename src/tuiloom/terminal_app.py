from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, Queue
from sys import stdout
from threading import current_thread, main_thread

from tuiloom._message_registry import MessageRegistry
from tuiloom.command import CommandBehavior, CommandContext, GlobalCommand
from tuiloom.content_panel import ContentPanel
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.key_binding import KeyBinding, KeyMap
from tuiloom.output_capture import OutputCapture
from tuiloom.output_task import OutputTaskSession
from tuiloom.render.content_renderer import ContentSource
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
    abandoned: bool = False


class TerminalApp:
    """Configure and run a Tuiloom application in an interactive terminal."""

    def __init__(
        self,
        name: str,
        global_content_source: ContentSource | None = None,
        *,
        keymap: KeyMap | None = None,
    ) -> None:
        """Create an application and its application-wide registries.

        Args:
            name: Application name displayed in every menu box.
            global_content_source: Default content inherited by menus.
            keymap: Custom system bindings, or ``None`` for defaults.
        """
        self._name = name
        self._global_content_source = global_content_source
        self._keymap = keymap if keymap is not None else KeyMap()
        self._keymap._set_external_validator(self._validate_system_binding)
        self._global_commands: list[GlobalCommand] = []
        self._main_menu: TerminalMenu | None = None
        self._message_registry = MessageRegistry()
        self._output_capture = OutputCapture()
        self._active_output_task: _OutputTaskRegistration | None = None
        self._output_task_outcomes: Queue[_OutputTaskRegistration] = Queue()
        self._input_handler: InputHandler | None = None

    @property
    def name(self) -> str:
        """Return the application name displayed in all menus."""
        return self._name

    @property
    def global_content_source(self) -> ContentSource | None:
        """Return the content source inherited by menus created without one."""
        return self._global_content_source

    @property
    def keymap(self) -> KeyMap:
        """Return the configurable application system key map."""
        return self._keymap

    @property
    def global_commands(self) -> tuple[GlobalCommand, ...]:
        """Return global-command handles as an immutable metadata view."""
        return tuple(self._global_commands)

    @property
    def main_menu(self) -> TerminalMenu | None:
        """Return the registered main menu, if one exists."""
        return self._main_menu

    def set_main_menu(self, menu: TerminalMenu) -> None:
        """Register an application-owned menu as the root Quit menu."""
        if menu.app is not self:
            raise ValueError("Main menu must belong to this TerminalApp")
        previous = self._main_menu
        if previous is not None and previous is not menu:
            previous.set_exit_label("Back")
        self._main_menu = menu
        menu.set_exit_label("Quit")

    def add_global_command(
        self,
        binding: KeyBinding,
        label: str,
        behavior: CommandBehavior,
    ) -> GlobalCommand:
        """Register an invisible command invoked immediately by one binding.

        Raises:
            ValueError: If the binding collides with navigation or another
                global command. No registry mutation occurs on failure.
        """
        self._validate_global_binding(binding)
        command = GlobalCommand(self, binding, label, behavior)
        self._global_commands.append(command)
        return command

    def set_global_command_binding(
        self, command: GlobalCommand, binding: KeyBinding
    ) -> None:
        """Atomically replace a global command's binding."""
        self._require_global(command)
        self._validate_global_binding(binding, excluding=command)
        command._binding = binding

    def set_global_command_label(self, command: GlobalCommand, label: str) -> None:
        """Replace a global command label used by user-built help displays."""
        self._require_global(command)
        command._label = label

    def set_global_command_behavior(
        self, command: GlobalCommand, behavior: CommandBehavior
    ) -> None:
        """Replace an application-level global callback."""
        self._require_global(command)
        command._behavior = behavior

    def add_message(self, key: str, text: str) -> None:
        """Register a custom static application message."""
        self._message_registry.add_message(key, text)

    def disable_message(self, key: str) -> None:
        """Disable a registered message across every menu."""
        self._message_registry.disable(key)

    def enable_message(self, key: str) -> None:
        """Re-enable a globally disabled message."""
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
        behavior = menu._global_behavior(command)
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
        if registration.abandoned:
            registration.menu._abandon_output_task(registration.session)
            return registration.menu
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

    def _stop_and_quit_output_task(self, menu: TerminalMenu) -> None:
        registration = self._active_output_task
        if registration is None:
            return
        registration.on_success = None
        registration.on_error = None
        registration.abandoned = True
        registration.session.cancel()
        registration.menu._abandon_output_task(registration.session)

    def _shutdown_output_task(self) -> None:
        """Cancel and join any task before terminal and capture restoration."""
        registration = self._active_output_task
        if registration is None:
            return
        registration.on_success = None
        registration.on_error = None
        self._active_output_task = None
        registration.session.cancel()
        registration.menu._abandon_output_task(registration.session)
        registration.session.join()

    def run(self) -> None:
        """Run the main menu as a blocking interactive main-thread call.

        The call requires a real terminal and the Python main thread. Terminal
        screen and input state are restored even when rendering or callbacks
        raise an exception.
        """
        main_menu = self._main_menu
        if main_menu is None:
            raise RuntimeError("Cannot run TerminalApp: no main menu has been set")
        if current_thread() is not main_thread():
            raise RuntimeError("TerminalApp.run() must execute on the main thread")

        with self._output_capture.install():
            self._input_handler = InputHandler()
            try:
                self._enter_terminal_screen()
                main_menu.run()
            finally:
                self._shutdown_output_task()
                self._input_handler.close()
                self._input_handler = None
                self._leave_terminal_screen()

    def _enter_terminal_screen(self) -> None:
        stdout.write("\033[?1049h\033[2J\033[H\033[?25l")
        stdout.write("\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1007l")
        stdout.flush()

    def _leave_terminal_screen(self) -> None:
        stdout.write("\033[?25h")
        stdout.write("\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1007l")
        stdout.write("\033[?1049l")
        stdout.flush()
