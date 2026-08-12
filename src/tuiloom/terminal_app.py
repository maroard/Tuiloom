from collections.abc import Callable
from sys import stdout

from tuiloom._message_registry import MessageRegistry
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.render.content_renderer import ContentSource
from tuiloom.screen_context.screen_context import CommandDict, ScreenContext
from tuiloom.terminal_menu import TerminalMenu


class TerminalApp:
    """Configure and run a Tuiloom application in the active terminal.

    The application owns global content, commands, and messages, creates the
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
        self.main_menu: TerminalMenu | None = None

        self._message_registry = MessageRegistry()

        # Created only while run() is active.
        self.input_handler: InputHandler | None = None

    def set_main_menu(
        self,
        title: str,
        name: str = "Main Menu",
        width: int | None = None,
    ) -> TerminalMenu:
        """Create and register the application's main menu.

        Args:
            title: Heading displayed at the top of the menu.
            name: Internal menu name used in contextual messages.
            width: Inner menu width, or ``None`` to determine it automatically.

        Returns:
            The configured main menu, ready for commands and content.
        """
        menu = TerminalMenu(
            app=self,
            screen_context=ScreenContext(
                app_name=self._name,
                menu_name=name,
                title=title,
                commands={},
                width=width,
            ),
            content_source=self.global_content_source,
        )

        self.main_menu = menu
        menu.set_exit_command_label("Quit")

        return menu

    def add_global_command(
        self,
        key: str,
        name: str,
        behavior: Callable[[], None],
    ) -> None:
        """Register a command that is available in every menu.

        Sequences entered by the user dispatch multiple individually registered
        commands.

        Args:
            key: Single alphabetic character used to invoke the command.
            name: Label describing the command.
            behavior: Zero-argument callable invoked by the command.

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

    def _handle_global_command(self, command: str) -> bool:
        """Execute a sequence of registered global commands atomically."""
        if not command:
            return False

        actions_to_proceed: list[Callable[[], None]] = []

        for char in command:
            command_data = self.global_commands.get(char.upper())

            if command_data is None:
                return False

            actions_to_proceed.append(command_data[0])

        for action in actions_to_proceed:
            action()

        return True

    def run(self) -> None:
        """Run the main menu and restore the terminal when it finishes.

        Raises:
            RuntimeError: If no main menu has been configured.
        """
        if self.main_menu is None:
            raise RuntimeError("Cannot run TerminalApp: no main menu has been set")

        self.input_handler = InputHandler()

        try:
            self._enter_terminal_screen()
            self.main_menu.run()

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
