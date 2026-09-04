from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import TYPE_CHECKING, Literal, cast
from warnings import warn

from wcwidth import iter_graphemes

from tuiloom._message_registry import MessageKey
from tuiloom.command import (
    CommandBehavior,
    CommandContext,
    GlobalCommand,
    InputBehavior,
    MenuCommand,
)
from tuiloom.content_panel import ContentPanel
from tuiloom.event_loop.event_loop import EventLoop
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.key_binding import KeyBinding
from tuiloom.output_task import OutputTaskSession
from tuiloom.render.content_renderer import ContentRenderer, ContentSource
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import AutoScrollMode, TerminalRenderer
from tuiloom.screen_context.screen_context import ScreenContext
from tuiloom.task_exit import TaskExitView

if TYPE_CHECKING:
    from tuiloom.terminal_app import TerminalApp


class TerminalMenu:
    """Configure selectable commands, content, alerts, and messages."""

    def __init__(
        self,
        app: TerminalApp,
        screen_context: ScreenContext,
        content_source: ContentSource | None = None,
        content_spacing: bool = True,
        show: bool = True,
        auto_scroll: AutoScrollMode | None = None,
    ) -> None:
        """Create a menu owned by ``app``.

        ``content_spacing`` inserts exactly one blank row between the content
        and menu boxes. A missing local source inherits application content.
        """
        if not isinstance(content_spacing, bool):
            raise TypeError("content_spacing must be a bool")
        self._app = app
        self._screen_context = screen_context
        self._content_source = (
            content_source if content_source is not None else app.global_content_source
        )
        self._content_description = "Content in progress"
        self._content_spacing = content_spacing
        if not isinstance(show, bool):
            raise TypeError("TerminalMenu.show must be a bool")
        self._show = show
        self._commands: list[MenuCommand] = []
        self._exit_label = "Back"
        self._exit_label_explicit = False
        self._selected_index = 0
        self._focused_panel: ContentPanel | None = None
        self._running = False
        self._hard_exit_requested = False

        self._input_buffer = ""
        self._input_behavior: InputBehavior | None = None
        self._input_prompt: str | None = None
        self._input_hidden = False
        self._alert_text: str | None = None
        self._alert_behavior: CommandBehavior | None = None
        self._alert_prompt: str | None = None

        self._output_task_session: OutputTaskSession | None = None
        self._output_task_panel: ContentPanel | None = None
        self._disabled_messages: set[str] = set()
        self._disabled_global_commands: set[GlobalCommand] = set()
        self._global_overrides: dict[GlobalCommand, CommandBehavior] = {}
        self._task_exit: TaskExitView | None = None

        self._content_renderer: ContentRenderer | None = None
        self._menu_renderer: MenuRenderer | None = None
        self._terminal_renderer: TerminalRenderer | None = None
        self._event_loop: EventLoop | None = None
        self._auto_scroll: AutoScrollMode | None = None
        self._content_panels: list[ContentPanel] = []
        self._primary_content_panel: ContentPanel | None = None
        self.auto_scroll = auto_scroll
        if self._content_source is not None:
            self._primary_content_panel = ContentPanel(
                self,
                self._content_source,
                self._content_description,
                self._auto_scroll,
            )
            self._content_panels.append(self._primary_content_panel)

    @property
    def app(self) -> TerminalApp:
        """Return the application that owns this menu."""
        return self._app

    @property
    def screen_context(self) -> ScreenContext:
        """Return this menu's configurable display context."""
        return self._screen_context

    @property
    def commands(self) -> tuple[MenuCommand, ...]:
        """Return an immutable ordered view of user command handles."""
        return tuple(self._commands)

    @property
    def content_panels(self) -> tuple[ContentPanel, ...]:
        """Return an immutable ordered view of this menu's content panels."""
        return tuple(self._content_panels)

    @property
    def is_main(self) -> bool:
        """Return whether this is the application's registered root menu."""
        return self is self.app.main_menu

    @property
    def show(self) -> bool:
        """Return whether this menu is currently rendered."""
        return self._show

    @show.setter
    def show(self, value: bool) -> None:
        """Show or fully clear the menu while leaving its loop and tasks active."""
        if not isinstance(value, bool):
            raise TypeError("TerminalMenu.show must be a bool")
        self._show = value
        self._invalidate_renderer()

    @property
    def auto_scroll(self) -> AutoScrollMode | None:
        """Return the iterator auto-scroll policy."""
        return self._auto_scroll

    @auto_scroll.setter
    def auto_scroll(self, mode: AutoScrollMode | None) -> None:
        """Set ``smart``, ``strict``, or disabled iterator following."""
        if mode not in (None, "smart", "strict"):
            raise ValueError("auto_scroll must be 'smart', 'strict', or None")
        if mode == self._auto_scroll:
            return
        if self._primary_content_panel is not None:
            self._primary_content_panel.set_auto_scroll(mode)
        else:
            self._auto_scroll = mode
        if self._terminal_renderer is not None:
            self._terminal_renderer.reset_stream_auto_scroll()

    def add_content_panel(
        self,
        content_source: ContentSource,
        *,
        description: str = "Content in progress",
        auto_scroll: AutoScrollMode | None = None,
        position: int | None = None,
    ) -> ContentPanel:
        """Add an independently rendered content panel and return its handle."""
        self._validate_auto_scroll(auto_scroll)
        insert_at = self._validate_content_position(position, allow_end=True)
        panel = ContentPanel(self, content_source, description, auto_scroll)
        self._content_panels.insert(insert_at, panel)
        if self._running and self._event_loop is not None:
            self._event_loop.add_content_panel(panel)
        self._invalidate_renderer()
        return panel

    def _set_content_panel_source(
        self,
        panel: ContentPanel,
        content_source: ContentSource,
    ) -> None:
        """Replace one owned panel's source without changing its identity."""
        self._require_content_panel(panel)
        panel._smart_auto_scroll_active = True
        panel._pending_auto_scroll = None
        if self._running and self._event_loop is not None:
            self._event_loop.replace_content_panel(panel, content_source)
        else:
            panel._source = content_source
            panel._renderer = ContentRenderer(content_source)
            panel._viewport = None
        if panel is self._primary_content_panel:
            self._content_source = content_source

    def _set_content_panel_description(
        self,
        panel: ContentPanel,
        description: str,
    ) -> None:
        """Replace the visible and shutdown description of one panel."""
        self._require_content_panel(panel)
        panel._description = description
        if panel._worker is not None:
            panel._worker.description = description
        if panel is self._primary_content_panel:
            self._content_description = description
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
        panel._smart_auto_scroll_active = True
        panel._pending_auto_scroll = None
        if panel is self._primary_content_panel:
            self._auto_scroll = mode

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
        if panel is self._primary_content_panel:
            self._primary_content_panel = None
            self._content_source = None
        panel._removed = True
        if self._running and self._event_loop is not None:
            self._event_loop.retire_content_panel(panel)
        if was_focused:
            self._focused_panel = (
                self._content_panels[removed_position]
                if removed_position < len(self._content_panels)
                else None
            )
        else:
            self._normalize_focus()
        self._invalidate_renderer()

    def add_command(
        self,
        label: str,
        behavior: CommandBehavior,
        *,
        position: int | None = None,
    ) -> MenuCommand:
        """Add a selectable command and return its stable mutation handle."""
        insert_at = self._validate_position(position, allow_end=True)
        selected = (
            self._commands[self._selected_index]
            if self._selected_index < len(self._commands)
            else None
        )
        command = MenuCommand(self, label, behavior)
        self._commands.insert(insert_at, command)
        if selected is not None:
            self._selected_index = self._commands.index(selected)
        self._normalize_selection()
        return command

    def add_menu(
        self,
        submenu: TerminalMenu,
        label: str,
        *,
        position: int | None = None,
    ) -> MenuCommand:
        """Add an application-owned submenu command and return its handle."""
        if submenu.app is not self.app:
            raise ValueError("Submenu must belong to the same TerminalApp")
        return self.add_command(
            label,
            lambda context: context.app.push_menu(submenu),
            position=position,
        )

    def set_command_label(self, command: MenuCommand, label: str) -> None:
        """Rename an owned command without changing its identity."""
        self._require_command(command)
        command._label = label

    def delete_command(self, command: MenuCommand) -> None:
        """Atomically remove an owned command and invalidate its handle."""
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

        for index in range(removed_position, len(self._commands)):
            if self._commands[index].enabled:
                self._selected_index = index
                return
        for index in range(removed_position - 1, -1, -1):
            if self._commands[index].enabled:
                self._selected_index = index
                return
        self._selected_index = len(self._commands)

    def set_command_behavior(
        self, command: MenuCommand, behavior: CommandBehavior
    ) -> None:
        """Replace an owned command callback."""
        self._require_command(command)
        command._behavior = behavior

    def move_command(self, command: MenuCommand, position: int) -> None:
        """Move an owned command to a zero-based position atomically."""
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
        """Prevent an owned command from being selected or activated."""
        self._require_command(command)
        command._enabled = False
        self._normalize_selection()

    def enable_command(self, command: MenuCommand) -> None:
        """Make a disabled owned command selectable again."""
        self._require_command(command)
        command._enabled = True
        self._normalize_selection()

    def set_exit_label(self, label: str) -> None:
        """Rename the automatic final Back/Quit option."""
        self._exit_label = label
        self._exit_label_explicit = True

    def set_global_command_behavior(
        self, command: GlobalCommand, behavior: CommandBehavior
    ) -> None:
        """Override one application global callback only in this menu."""
        self.app._require_global(command)
        self._global_overrides[command] = behavior

    def clear_global_command_behavior(self, command: GlobalCommand) -> None:
        """Remove a local global callback override."""
        self.app._require_global(command)
        self._global_overrides.pop(command, None)

    def disable_global_command(self, command: GlobalCommand) -> None:
        """Disable one application global command locally."""
        self.app._require_global(command)
        self._disabled_global_commands.add(command)

    def enable_global_command(self, command: GlobalCommand) -> None:
        """Re-enable one locally disabled global command."""
        self.app._require_global(command)
        self._disabled_global_commands.discard(command)

    def set_content_source(
        self,
        content_source: ContentSource,
        *,
        description: str = "Content in progress",
    ) -> None:
        """Replace content with static text, lines, an iterator, or callable."""
        panel = self._primary_content_panel
        if panel is None:
            panel = self.add_content_panel(
                content_source,
                description=description,
                auto_scroll=self._auto_scroll,
                position=0,
            )
            self._primary_content_panel = panel
            self._content_source = content_source
            self._content_description = description
            return
        panel.set_description(description)
        panel.set_source(content_source)

    def run_with_output[T](
        self,
        action: Callable[[], T],
        *,
        on_success: Callable[[T], None],
        on_error: Callable[[Exception], None],
        description: str = "Task in progress",
    ) -> None:
        """Run blocking work while capturing Python stdout/stderr as content.

        Capture covers ``print`` and Python writes to ``sys.stdout`` and
        ``sys.stderr``. It cannot capture subprocess output or direct POSIX file
        descriptor writes. Root-menu exit offers stop, wait, and cancel modes.
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
                session.iter_output(),
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
        behavior: InputBehavior,
        *,
        hidden: bool = False,
    ) -> None:
        """Begin free text entry; ``hidden=True`` masks each grapheme."""
        self._input_behavior = behavior
        self._input_prompt = prompt
        self._input_hidden = hidden
        self._input_buffer = ""

    def leave_input_mode(self) -> None:
        """Leave free text entry and discard its buffer and prompt."""
        self._input_behavior = None
        self._input_prompt = None
        self._input_hidden = False
        self._input_buffer = ""

    def show_alert(
        self,
        text: str,
        *,
        on_confirm: CommandBehavior | None = None,
        prompt: str | None = None,
    ) -> None:
        """Replace the menu body with a blocking or confirmable alert.

        A callback enables Enter confirmation. The alert is cleared only when
        that callback returns normally; global commands remain available.
        """
        self._alert_text = text
        self._alert_behavior = on_confirm
        self._alert_prompt = (
            prompt
            if prompt is not None
            else "Press Enter to continue"
            if on_confirm is not None
            else None
        )

    def clear_alert(self) -> None:
        """Clear the alert and reveal any suspended input state unchanged."""
        self._alert_text = None
        self._alert_behavior = None
        self._alert_prompt = None

    def show_message(self, key: str) -> bool:
        """Show an enabled registered message without disturbing it on failure."""
        self.app._validate_message_key(key)
        if not self.is_message_enabled(key):
            return False
        context: dict[str, object] = {}
        if key == MessageKey.NO_CONTENT_SOURCE:
            context["menu_name"] = self.screen_context.menu_name
        elif key == MessageKey.UNKNOWN_COMMAND:
            context["command"] = ""
        message = self.app._get_message(key, **context)
        if message is None:
            return False
        self.screen_context.message = message
        return True

    def clear_message(self) -> None:
        """Clear the current footer message."""
        self.screen_context.message = None

    def disable_message(self, key: str) -> None:
        """Validate and suppress one message locally."""
        self.app._validate_message_key(key)
        self._disabled_messages.add(key)

    def enable_message(self, key: str) -> None:
        """Validate and remove local suppression for one message."""
        self.app._validate_message_key(key)
        self._disabled_messages.discard(key)

    def is_message_enabled(self, key: str) -> bool:
        """Return combined local and application-wide message enablement."""
        self.app._validate_message_key(key)
        return key not in self._disabled_messages and self.app._is_message_enabled(key)

    def run(self) -> None:
        """Deprecated: request that the running application push this menu.

        Use :meth:`TerminalApp.push_menu` instead. This compatibility method
        never starts a nested event loop.
        """
        warn(
            "TerminalMenu.run() is deprecated; use TerminalApp.push_menu()",
            DeprecationWarning,
            stacklevel=2,
        )
        if self.app._running:
            self.app.push_menu(self)
            return
        if self.app._input_handler is None:
            raise RuntimeError("Cannot run TerminalMenu outside TerminalApp.run()")
        self._prepare_open()
        self._initialize_runtime()
        loop = self._event_loop
        if loop is None:
            raise RuntimeError("Menu runtime was not initialized")
        try:
            loop.run()
        finally:
            if self._hard_exit_requested:
                loop.abandon()
            else:
                loop.close()
            self._event_loop = None

    def _prepare_open(self) -> None:
        """Reset transient navigation state whenever this menu becomes visible."""
        self._input_buffer = ""
        self._focused_panel = None
        self._selected_index = 0
        self._normalize_selection()
        self._invalidate_renderer()

    def _initialize_runtime(self) -> None:
        """Create renderers and workers the first time this menu is opened."""
        self._running = True
        source = self._resolve_content_source()
        primary = self._primary_content_panel
        self._content_renderer = (
            primary._renderer
            if primary is not None
            else ContentRenderer(source if source is not None else "")
        )
        self._menu_renderer = MenuRenderer(self)
        self._terminal_renderer = TerminalRenderer(
            menu=self,
            menu_renderer=self._menu_renderer,
            content_renderer=self._content_renderer,
            content_spacing=self._content_spacing,
        )
        self._event_loop = self._create_event_loop()

    def stop(self) -> None:
        """Request Back/Quit, presenting choices while background work is active."""
        at_root = len(self.app._menu_stack) <= 1 and (
            self in self.app._menu_stack or not self.app._menu_stack and self.is_main
        )
        if at_root and self._current_exit_panels():
            self._begin_task_exit_choice()
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

    def _move_selection(self, delta: int) -> None:
        selectable = self._selectable_indices()
        current = selectable.index(self._selected_index)
        self._selected_index = selectable[(current + delta) % len(selectable)]

    def _resolve_content_source(self) -> ContentSource | None:
        return self._content_source

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
        if self._focused_panel not in self._visible_content_panels():
            self._focused_panel = None

    def _cycle_focus(self) -> None:
        focusable: list[ContentPanel | None] = [
            None,
            *self._visible_content_panels(),
        ]
        try:
            current = focusable.index(self._focused_panel)
        except ValueError:
            current = 0
        self._focused_panel = focusable[(current + 1) % len(focusable)]

    def _create_event_loop(self) -> EventLoop:
        if (
            self.app._input_handler is None
            or self._content_renderer is None
            or self._menu_renderer is None
            or self._terminal_renderer is None
        ):
            raise RuntimeError("Cannot create event loop before menu resources")
        return EventLoop(
            menu=self,
            input_handler=self.app._input_handler,
            menu_renderer=self._menu_renderer,
            terminal_renderer=self._terminal_renderer,
            content_renderer=self._content_renderer,
        )

    def _handle_event(self, event: InputEvent) -> None:
        binding = event.binding
        if self._task_exit is not None:
            self._handle_task_exit_event(event)
            return
        if not self.show:
            if binding is not None and self.app._handle_global_command(binding, self):
                self._invalidate_renderer()
            elif binding is not None and self.app.keymap.action_for(binding) == "back":
                self.stop()
            return
        if self._input_behavior is not None and self._alert_text is None:
            self._handle_input_event(event)
            return
        if binding is None:
            if event.text:
                self._show_automatic_message(
                    MessageKey.UNKNOWN_COMMAND, command=event.text
                )
            return
        if self.app._handle_global_command(binding, self):
            self._invalidate_renderer()
            return
        action = self.app.keymap.action_for(binding)
        if self._alert_text is not None:
            if action == "activate" and self._alert_behavior is not None:
                behavior = self._alert_behavior
                behavior(CommandContext(self.app, self, None, binding))
                self.clear_alert()
            elif action == "back":
                self.stop()
            return
        if action == "focus" and self._has_content():
            self._cycle_focus()
        elif action == "back":
            self.stop()
        elif self._focused_panel is None:
            if action == "up":
                self._move_selection(-1)
            elif action == "down":
                self._move_selection(1)
            elif action == "activate":
                self._activate_selection(binding)
        elif action in {"up", "down", "left", "right"}:
            self._scroll_content(cast(Literal["up", "down", "left", "right"], action))
        elif action is None and event.text:
            self._show_automatic_message(MessageKey.UNKNOWN_COMMAND, command=event.text)
        self._invalidate_renderer()

    def _handle_input_event(self, event: InputEvent) -> None:
        binding = event.binding
        action = self.app.keymap.action_for(binding) if binding is not None else None
        if action == "activate":
            behavior = self._input_behavior
            if behavior is not None:
                behavior(self._input_buffer)
            return
        if action == "back":
            self.leave_input_mode()
            return
        if (
            binding is not None
            and binding.key == "backspace"
            and not any((binding.ctrl, binding.alt, binding.shift))
        ):
            graphemes = list(iter_graphemes(self._input_buffer))
            self._input_buffer = "".join(graphemes[:-1])
            return
        if event.text:
            self._input_buffer += event.text

    def _activate_selection(self, binding: KeyBinding) -> None:
        if self._selected_index == len(self._commands):
            self.stop()
            return
        command = self._commands[self._selected_index]
        if not command.enabled:
            return
        command.behavior(CommandContext(self.app, self, command, binding))

    def _scroll_content(
        self, direction: Literal["up", "down", "left", "right"]
    ) -> None:
        renderer = self._terminal_renderer
        panel = self._focused_panel
        if renderer is None or panel is None:
            return
        renderer.scroll_panel(panel, direction)

    def _display_input_buffer(self) -> str:
        if not self._input_hidden:
            return self._input_buffer
        return "*" * len(list(iter_graphemes(self._input_buffer)))

    def _is_global_command_enabled(self, command: GlobalCommand) -> bool:
        return command not in self._disabled_global_commands

    def _global_behavior(self, command: GlobalCommand) -> CommandBehavior:
        return self._global_overrides.get(command, command.behavior)

    def _detach_output_task(self, session: OutputTaskSession) -> None:
        if session is not self._output_task_session:
            return
        self._output_task_session = None
        panel = self._output_task_panel
        self._output_task_panel = None
        if panel is None or panel._removed:
            return
        if panel._renderer.rendered_content.finished:
            panel.remove()
        else:
            panel._remove_when_finished = True

    def _abandon_output_task(self, session: OutputTaskSession) -> None:
        if session is self._output_task_session:
            self._output_task_session = None
            panel = self._output_task_panel
            self._output_task_panel = None
            if panel is not None:
                panel._remove_when_finished = True

    def _show_automatic_message(self, key: str, **context: object) -> bool:
        if not self.is_message_enabled(key):
            return False
        message = self.app._get_message(key, **context)
        if message is None:
            return False
        self.screen_context.message = message
        return True

    def _begin_task_exit_choice(self) -> None:
        if self._task_exit is not None:
            return
        panels = self._current_exit_panels()
        if not panels:
            self._stop_immediately()
            return
        self._task_exit = TaskExitView(
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
                self._scroll_content(
                    cast(Literal["up", "down", "left", "right"], action)
                )
        elif action == "up":
            view.move(-1)
        elif action == "down":
            view.move(1)
        elif action == "activate" and view.rows:
            self._activate_task_exit_row(view.rows[view.selected_index])
        self._invalidate_renderer()

    def _activate_task_exit_row(self, row: str) -> None:
        view = self._task_exit
        if view is None:
            return
        if row == "Cancel":
            self._cancel_task_exit()
            return
        if row == "Wait and quit":
            view.mode = "waiting"
            view.selected_index = 0
            view.wait_started_at = monotonic()
            view.wait_phase = -1
            return
        if row == "Force quit":
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
