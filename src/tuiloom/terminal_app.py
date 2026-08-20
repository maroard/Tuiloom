from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, Queue
from sys import stdout

from tuiloom._message_registry import MessageRegistry
from tuiloom.command import CommandBehavior, CommandContext, CommandDict
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.output_capture import OutputCapture
from tuiloom.output_task import OutputTaskSession
from tuiloom.render.content_renderer import ContentSource
from tuiloom.terminal_menu import TerminalMenu


@dataclass(frozen=True, slots=True)
class _OutputTaskRegistration:
    """Associate one captured task with its originating menu callbacks."""

    menu: TerminalMenu
    session: OutputTaskSession
    on_success: Callable[[object], None]
    on_error: Callable[[Exception], None]


class TerminalApp:
    """Configure and run a Tuiloom application in the active terminal.

    The application owns global content, commands, messages, and its registered
    main menu, and restores the terminal state after execution.
    """

    def __init__(
        self,
        name: str,
        global_content_source: ContentSource | None = None,
    ) -> None:
        """Create an application.

        Args:
            name: Application name displayed in every menu.
            global_content_source: Default content for menus without their own
                content source.
        """
        self._name = name
        self.global_content_source = global_content_source

        self.global_commands: CommandDict = {}
        self._main_menu: TerminalMenu | None = None

        self._message_registry = MessageRegistry()
        self._output_capture = OutputCapture()
        self._active_output_task: _OutputTaskRegistration | None = None
        self._output_task_outcomes: Queue[_OutputTaskRegistration] = Queue()

        # Created only while run() is active.
        self.input_handler: InputHandler | None = None

    @property
    def name(self) -> str:
        """Return the public application name used by menu contexts.

        Returns:
            The name supplied when this application was created.
        """
        return self._name

    @property
    def main_menu(self) -> TerminalMenu | None:
        """Return the registered main menu, if one exists.

        Returns:
            The read-only registered menu reference, or ``None``.
        """
        return self._main_menu

    def set_main_menu(self, menu: TerminalMenu) -> None:
        """Register an existing menu as the application's main menu.

        Args:
            menu: Menu owned by this application.

        Raises:
            ValueError: If ``menu`` belongs to another application.
        """
        if menu.app is not self:
            raise ValueError("Main menu must belong to this TerminalApp")

        previous_menu = self._main_menu
        if previous_menu is not None and previous_menu is not menu:
            previous_menu.set_command_label("0", "Back")

        menu.set_command_label("0", "Quit")
        self._main_menu = menu

    def add_global_command(
        self,
        key: str,
        name: str,
        behavior: CommandBehavior,
    ) -> None:
        """Register a command that is available in every menu.

        The complete user input resolves one exact normalized global key.

        Args:
            key: Single alphabetic character used to invoke the command.
            name: Label describing the command.
            behavior: Callback invoked with a context describing this execution.

        Raises:
            ValueError: If ``key`` is not a single alphabetic character.
        """
        if len(key) != 1 or not key.isalpha():
            raise ValueError(
                "Global command keys must be a single alphabetic character, "
                f"got {key!r}"
            )

        self.global_commands[key.upper()] = (behavior, name)

    def add_message(self, key: str, text: str) -> None:
        """Register a custom application message available to every menu.

        Args:
            key: Unique, nonempty identifier for the message.
            text: Static text returned when the message is requested.

        Raises:
            ValueError: If ``key`` is empty or already registered.
        """
        self._message_registry.add_message(key, text)

    def disable_message(self, key: str) -> None:
        """Disable a registered message in every application menu.

        Args:
            key: Registered message identifier.

        Raises:
            KeyError: If ``key`` is not registered.
        """
        self._message_registry.disable(key)

    def enable_message(self, key: str) -> None:
        """Re-enable a globally disabled application message.

        A message can still be suppressed locally by an individual menu.

        Args:
            key: Registered message identifier.

        Raises:
            KeyError: If ``key`` is not registered.
        """
        self._message_registry.enable(key)

    def _get_message(self, key: str, **context: object) -> str | None:
        """Resolve a message through the application's private registry."""
        return self._message_registry.get(key, **context)

    def _handle_global_command(self, command: str, menu: TerminalMenu) -> bool:
        """Resolve and execute one exact normalized global command."""
        command_key = command.upper()
        command_data = self.global_commands.get(command_key)

        if command_data is None:
            return False

        action = command_data[0]
        action(CommandContext(app=self, menu=menu, command_key=command_key))
        return True

    def _start_output_task(
        self,
        menu: TerminalMenu,
        action: Callable[[], object],
        on_success: Callable[[object], None],
        on_error: Callable[[Exception], None],
    ) -> OutputTaskSession:
        """Start one application-owned captured-output task."""
        if self._active_output_task is not None:
            raise RuntimeError("Another output task is already running")

        session = OutputTaskSession()
        registration = _OutputTaskRegistration(
            menu=menu,
            session=session,
            on_success=on_success,
            on_error=on_error,
        )
        self._active_output_task = registration
        session.start(
            action,
            self._output_capture,
            lambda completed: self._output_task_outcomes.put(registration),
        )
        return session

    def _dispatch_output_task_outcome(self) -> TerminalMenu | None:
        """Apply one completed output-task result on the UI thread."""
        try:
            registration = self._output_task_outcomes.get_nowait()
        except Empty:
            return None

        if registration is not self._active_output_task:
            return None

        self._active_output_task = None
        registration.menu._detach_output_task(registration.session)
        outcome = registration.session.outcome

        if outcome is None:
            raise RuntimeError("Completed output task has no outcome")

        if outcome.error is None:
            registration.on_success(outcome.result)
        else:
            registration.on_error(outcome.error)

        return registration.menu

    def run(self) -> None:
        """Run the main menu and restore the terminal when it finishes.

        Raises:
            RuntimeError: If no main menu has been configured.
        """
        main_menu = self._main_menu
        if main_menu is None:
            raise RuntimeError("Cannot run TerminalApp: no main menu has been set")

        with self._output_capture.install():
            self.input_handler = InputHandler()

            try:
                self._enter_terminal_screen()
                main_menu.run()

            finally:
                self.input_handler.close()
                self.input_handler = None
                self._leave_terminal_screen()

    # Switch to the alternate terminal screen and hide cursor affordances.
    def _enter_terminal_screen(self) -> None:
        """Enter the alternate terminal screen and hide the cursor."""
        stdout.write("\033[?1049h")
        stdout.write("\033[2J\033[H")
        stdout.write("\033[?25l")

        stdout.write("\033[?1000l")
        stdout.write("\033[?1002l")
        stdout.write("\033[?1003l")
        stdout.write("\033[?1006l")
        stdout.write("\033[?1007l")

        stdout.flush()

    # Restore terminal cursor state and leave the alternate screen.
    def _leave_terminal_screen(self) -> None:
        """Restore terminal affordances and leave the alternate screen."""
        stdout.write("\033[?25h")

        stdout.write("\033[?1000l")
        stdout.write("\033[?1002l")
        stdout.write("\033[?1003l")
        stdout.write("\033[?1006l")
        stdout.write("\033[?1007l")

        stdout.write("\033[?1049l")
        stdout.flush()
