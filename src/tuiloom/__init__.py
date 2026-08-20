"""Build typed terminal applications with menus and dynamic content."""

from tuiloom._message_registry import MessageKey
from tuiloom.command import (
    Command,
    CommandBehavior,
    CommandContext,
    CommandDict,
    InputBehavior,
)
from tuiloom.formatting import hyperlink
from tuiloom.render.content_renderer import ContentSource
from tuiloom.render.terminal_renderer import AutoScrollMode
from tuiloom.screen_context.screen_context import ScreenContext
from tuiloom.terminal_app import TerminalApp
from tuiloom.terminal_menu import TerminalMenu

__all__ = [
    "Command",
    "AutoScrollMode",
    "CommandBehavior",
    "CommandContext",
    "CommandDict",
    "InputBehavior",
    "hyperlink",
    "ContentSource",
    "ScreenContext",
    "TerminalApp",
    "TerminalMenu",
    "MessageKey",
]
