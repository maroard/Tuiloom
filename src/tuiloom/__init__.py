"""Build terminal applications with typed menus, callbacks and content sources.

Create a ``TerminalApp`` and a ``TerminalMenu`` with ``MenuDisplay`` settings,
register commands and ``ScreenContent`` panels, then call
``app.set_main_menu(menu)`` and ``app.run()`` on the main thread in a terminal.
Configuration and UI mutations belong on that thread; content producers and
captured output tasks run in background workers. See each object's docstring
for its complete parameter, ownership, timing and error contracts.

Attributes:
    CommandCallback: Callable accepting one ``CommandContext``; keyboard
        activation and command-level hover callbacks run on the UI thread and
        their return values are ignored.
    ChoiceCallback: Callable accepting one ``ChoiceContext`` for a committed
        option or option-level keyboard preview. Returns are ignored.
    InputCallback: Callable accepting the submitted plain-text ``str`` on the
        UI thread. Submission does not itself leave input mode; return ignored.
    KeyAction: One of ``"focus"``, ``"up"``, ``"down"``, ``"left"``,
        ``"right"``, ``"activate"`` or ``"back"`` for a ``KeyMap`` action.
    AutoScrollMode: ``"smart"`` follows new stream output unless scrolled away
        from the bottom; ``"strict"`` follows each new batch. Panel parameters
        also accept ``None`` for manual scrolling.
    MenuPresentation: ``"inline"`` places commands below content panels;
        ``"overlay"`` draws the command box over their layout.
    ContentRefreshMode: ``"resize"`` updates responsive content on layout changes
        and explicit refresh; ``"continuous"`` also updates at unchanged size.
    TextColor: Supported color name, integer palette index in ``0..255``, RGB
        tuple with three integer components in ``0..255``, or ``#RRGGBB`` string.
        See ``style()`` for the accepted color names and reset behavior.
"""

from tuiloom._message_registry import MessageKey
from tuiloom.animation import AnimatedText, AnimationFrame, rainbow_color
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
    PanelCommandCallback,
    PanelCommandContext,
    PanelKeyCommand,
)
from tuiloom.configuration import AutoScrollMode, ContentRefreshMode, MenuPresentation
from tuiloom.content_panel import ContentPanel
from tuiloom.content_row import ContentRow
from tuiloom.formatting import TextColor, hyperlink, style
from tuiloom.key_binding import KeyAction, KeyBinding, KeyMap
from tuiloom.menu_display import MenuDisplay
from tuiloom.render.terminal_text import display_width
from tuiloom.screen_content import ContentSize, ScreenContent
from tuiloom.status_bar import StatusBar
from tuiloom.terminal_app import TerminalApp
from tuiloom.terminal_menu import TerminalMenu

__all__ = [
    "AnimatedText",
    "AnimationFrame",
    "AutoScrollMode",
    "CommandCallback",
    "ChoiceCallback",
    "ChoiceContext",
    "ChoiceOption",
    "CommandContext",
    "ContentPanel",
    "ContentRow",
    "ContentRefreshMode",
    "ContentSize",
    "GlobalCommand",
    "InputCallback",
    "KeyAction",
    "KeyBinding",
    "KeyMap",
    "MenuCommand",
    "PanelCommandCallback",
    "PanelCommandContext",
    "PanelKeyCommand",
    "MenuChoice",
    "MenuPresentation",
    "MenuDisplay",
    "hyperlink",
    "ScreenContent",
    "StatusBar",
    "TerminalApp",
    "TerminalMenu",
    "MessageKey",
    "TextColor",
    "display_width",
    "rainbow_color",
    "style",
]
