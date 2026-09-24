"""Build typed terminal applications with menus and dynamic content."""

from tuiloom._message_registry import MessageKey
from tuiloom.command import (
    ChoiceBehavior,
    ChoiceContext,
    ChoiceOption,
    CommandBehavior,
    CommandContext,
    GlobalCommand,
    InputBehavior,
    MenuChoice,
    MenuCommand,
)
from tuiloom.content_panel import ContentPanel
from tuiloom.formatting import TextColor, hyperlink, style
from tuiloom.key_binding import KeyBinding, KeyMap
from tuiloom.render.terminal_renderer import AutoScrollMode
from tuiloom.render.terminal_text import display_width
from tuiloom.screen_content import ContentRefreshMode, ContentSize, ScreenContent
from tuiloom.screen_context.screen_context import ScreenContext
from tuiloom.terminal_app import TerminalApp
from tuiloom.terminal_menu import TerminalMenu

__all__ = [
    "AutoScrollMode",
    "CommandBehavior",
    "ChoiceBehavior",
    "ChoiceContext",
    "ChoiceOption",
    "CommandContext",
    "ContentPanel",
    "ContentRefreshMode",
    "ContentSize",
    "GlobalCommand",
    "InputBehavior",
    "KeyBinding",
    "KeyMap",
    "MenuCommand",
    "MenuChoice",
    "hyperlink",
    "ScreenContent",
    "ScreenContext",
    "TerminalApp",
    "TerminalMenu",
    "MessageKey",
    "TextColor",
    "display_width",
    "style",
]
