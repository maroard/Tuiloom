from __future__ import annotations

from time import sleep
from typing import TYPE_CHECKING

from tuiloom._message_registry import MessageKey
from tuiloom.command import (
    CommandBehavior,
    CommandContext,
    CommandDict,
    _without_context,
)
from tuiloom.input_handler.input_event import InputEvent, InputEventType
from tuiloom.render.content_renderer import ContentRenderer, ContentSource
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.screen_context.screen_context import ScreenContext

if TYPE_CHECKING:
    from tuiloom.terminal_app import TerminalApp


class TerminalMenu:
    """Configure commands, content, and messages for one application menu.

    A menu owns its local commands, content source, and message suppression
    state, and runs within the lifecycle of its parent application.
    """

    def __init__(
        self,
        app: TerminalApp,
        screen_context: ScreenContext,
        content_source: ContentSource | None = None,
        spacing_with_content: int = 1,
        show: bool = True,
    ) -> None:
        """Create a menu attached to an application.

        Args:
            app: Application that owns the menu and its shared resources.
            screen_context: Display state consumed when rendering the menu.
            content_source: Text, lines, stream, or callable rendered as the
                menu's content. ``None`` inherits the application's global
                content source.
            spacing_with_content: Number of blank lines between content and the
                menu controls.
            show: Initial visibility flag retained for application-controlled
                menu display.
        """
        self.app = app
        self.screen_context = screen_context
        self._content_source = (
            content_source if content_source is not None else app.global_content_source
        )
        self.spacing_with_content = spacing_with_content
        self.show = show

        self.running = False
        self._input_buffer = ""
        self._disabled_messages: set[str] = set()

        self.commands: CommandDict = self.screen_context.commands
        self.commands["0"] = (_without_context(self.stop), "Back")

        self.content_renderer: ContentRenderer | None = None
        self.menu_renderer: MenuRenderer | None = None
        self.terminal_renderer: TerminalRenderer | None = None

    @property
    def is_main(self) -> bool:
        """Check whether this menu is registered as the application's main menu.

        Returns:
            ``True`` when this object is the application's main menu.
        """
        return self is self.app.main_menu

    def add_command(
        self,
        name: str,
        behavior: CommandBehavior,
        index: int | None = None,
    ) -> None:
        """Add or replace a numbered menu command.

        Args:
            name: Label displayed for the command.
            behavior: Callback invoked with a context describing this execution.
            index: Command number, or ``None`` to use the next number.

        Raises:
            ValueError: If ``index`` is zero, which is reserved for exiting.
        """
        if index == 0:
            raise ValueError(
                "Command index 0 is reserved for Back/Quit. "
                "Use set_exit_command_label() to change its label."
            )

        if index is None:
            index = len(self.commands)

        self.commands[str(index)] = (behavior, name)

    def add_menu(
        self,
        menu: TerminalMenu,
        name: str,
        index: int | None = None,
    ) -> None:
        """Add another menu as a command that opens it.

        Args:
            menu: Menu to run when the command is selected.
            name: Label displayed for the command.
            index: Command number, or ``None`` to use the next number.
        """
        self.add_command(
            name=name,
            behavior=_without_context(menu.run),
            index=index,
        )

    def set_content_source(
        self,
        content_source: ContentSource,
    ) -> None:
        """Replace the content source used on the next run.

        Args:
            content_source: Supported text, line-list, iterator, or callable
                content source.
        """
        self._content_source = content_source

    def disable_message(self, key: str) -> None:
        """Suppress a registry message locally in this menu.

        Args:
            key: Registry key to add to this menu's local suppression set.
        """
        self._disabled_messages.add(key)

    def enable_message(self, key: str) -> None:
        """Remove a registry message from this menu's local suppression set.

        This cannot override a message disabled globally with
        :meth:`TerminalApp.disable_message`.

        Args:
            key: Registry key to stop suppressing locally.
        """
        self._disabled_messages.discard(key)

    def is_message_enabled(self, key: str) -> bool:
        """Inspect whether a registry message is not locally suppressed.

        Global registry state may still prevent the message from being displayed.

        Args:
            key: Registry key to inspect.

        Returns:
            ``True`` when the key is not in this menu's local suppression set.
        """
        return key not in self._disabled_messages

    def set_exit_command_label(self, label: str) -> None:
        """Change the label of the command numbered zero.

        Args:
            label: New label for the exit command.
        """
        behavior, _ = self.commands["0"]
        self.commands["0"] = (behavior, label)

    def run(self) -> None:
        """Run the menu until it is stopped.

        Raises:
            RuntimeError: If called outside :meth:`TerminalApp.run`.
        """
        if self.app.input_handler is None:
            raise RuntimeError("Cannot run TerminalMenu outside TerminalApp.run()")

        self.running = True
        self._input_buffer = ""

        if self._content_source is None:
            self.content_renderer = ContentRenderer("")
            self._handle_no_content_source()
        else:
            self.content_renderer = ContentRenderer(self._content_source)

        self.menu_renderer = MenuRenderer(self.screen_context)

        self.terminal_renderer = TerminalRenderer(
            menu_renderer=self.menu_renderer,
            content_renderer=self.content_renderer,
            spacing=self.spacing_with_content,
        )

        while self.running:
            self._render()

            event = self.app.input_handler.poll()

            if event is not None:
                self._handle_event(event)

            sleep(0.01)

    def _render(self) -> None:
        """Render the menu with the current command input."""
        if self.terminal_renderer is not None:
            self.terminal_renderer.render(self._input_buffer)

    def _handle_no_content_source(self) -> None:
        """Display the no-content message when it is enabled."""
        message_key = MessageKey.NO_CONTENT_SOURCE

        if not self.is_message_enabled(message_key):
            return

        self.screen_context.message = self.app._get_message(
            message_key,
            menu_name=self.screen_context.menu_name,
        )

    def _handle_event(self, event: InputEvent) -> None:
        """Dispatch one normalized input event to its internal handler."""
        event_type = event.type

        if event_type == "char":
            self._handle_char(event)

        elif event_type == "enter":
            self._handle_enter()

        elif event_type == "backspace":
            self._handle_backspace()

        elif event_type in ("up", "down", "left", "right"):
            self._handle_scroll(event_type)

        elif event_type == "escape":
            self._handle_escape()

    def _handle_char(self, event: InputEvent) -> None:
        """Append a character event to the current command buffer."""
        if event.value is not None:
            self._input_buffer += event.value

    def _handle_backspace(self) -> None:
        """Remove the last character from the current command buffer."""
        self._input_buffer = self._input_buffer[:-1]

    def _handle_enter(self) -> None:
        """Resolve and execute the command currently buffered by the menu."""
        command = self._input_buffer
        self._input_buffer = ""

        if self.app._handle_global_command(command, self):
            return

        command_data = self.commands.get(command)

        if command_data is None:
            self._handle_unknown_command(command)
            return

        action = command_data[0]
        action(CommandContext(app=self.app, menu=self, command_key=command))

    def _handle_unknown_command(self, command: str) -> None:
        """Display the unknown-command message when it is enabled."""
        message_key = MessageKey.UNKNOWN_COMMAND

        if not self.is_message_enabled(message_key):
            return

        self.screen_context.message = self.app._get_message(
            message_key,
            command=command,
        )

    def _handle_scroll(
        self,
        direction: InputEventType,
    ) -> None:
        """Forward a directional input event to the terminal renderer."""
        if self.terminal_renderer is None:
            return

        if direction == "up":
            self.terminal_renderer.scroll_up()

        elif direction == "down":
            self.terminal_renderer.scroll_down()

        elif direction == "left":
            self.terminal_renderer.scroll_left()

        elif direction == "right":
            self.terminal_renderer.scroll_right()

    def _handle_escape(self) -> None:
        """Stop the active menu in response to the Escape key."""
        self.stop()

    # Stop the active menu loop on the next iteration.
    def stop(self) -> None:
        """Request that the menu stop after the current loop iteration.

        Returns:
            ``None``; the loop observes the updated state on its next boundary.
        """
        self.running = False
