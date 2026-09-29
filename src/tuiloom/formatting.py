"""Format terminal strings while filtering unsafe control sequences.

Attributes:
    TextColor: A color name, an integer palette index from 0 to 255, an RGB
        tuple of three integer components from 0 to 255, or a ``#RRGGBB``
        string. Bool is not accepted as an index or RGB component. Names
        are case-sensitive; hexadecimal digits are case-insensitive.
"""

from re import fullmatch

from tuiloom.render.terminal_text import (
    is_safe_hyperlink_url,
    sanitize_hyperlink_text,
    sanitize_terminal_text,
)

type TextColor = str | int | tuple[int, int, int]
"""Terminal color: a supported name, palette index, RGB tuple or #RRGGBB text."""

_NAMED_COLORS = {
    "black": 0,
    "red": 1,
    "green": 2,
    "yellow": 3,
    "blue": 4,
    "magenta": 5,
    "cyan": 6,
    "white": 7,
    "bright_black": 8,
    "bright_red": 9,
    "bright_green": 10,
    "bright_yellow": 11,
    "bright_blue": 12,
    "bright_magenta": 13,
    "bright_cyan": 14,
    "bright_white": 15,
}
_NAMED_RGB_COLORS = {
    "orange": (255, 165, 0),
    "gray": (128, 128, 128),
    "dark_red": (127, 0, 0),
    "dark_green": (0, 127, 0),
    "dark_yellow": (127, 127, 0),
    "dark_blue": (0, 0, 127),
    "dark_magenta": (127, 0, 127),
    "dark_cyan": (0, 127, 127),
    "dark_orange": (127, 82, 0),
    "dark_gray": (64, 64, 64),
}
_STYLE_CODES = (
    ("bold", 1, 22),
    ("dim", 2, 22),
    ("italic", 3, 23),
    ("underline", 4, 24),
    ("strikethrough", 9, 29),
    ("reverse", 7, 27),
)


def _color_code(color: TextColor, *, background: bool) -> list[int]:
    prefix = 48 if background else 38

    if isinstance(color, bool):
        raise TypeError("A color index must be an integer, not bool")

    if isinstance(color, int):
        if not 0 <= color <= 255:
            raise ValueError("A color index must be between 0 and 255")
        return [prefix, 5, color]

    if isinstance(color, tuple):
        if len(color) != 3:
            raise TypeError("An RGB color must contain exactly three components")
        if any(
            isinstance(component, bool) or not isinstance(component, int)
            for component in color
        ):
            raise TypeError("RGB components must be integers, not bool")
        if any(not 0 <= component <= 255 for component in color):
            raise ValueError("RGB components must be between 0 and 255")
        return [prefix, 2, *color]

    if isinstance(color, str):
        named_index = _NAMED_COLORS.get(color)
        if named_index is not None:
            base = 40 if background else 30
            if named_index >= 8:
                base += 60
                named_index -= 8
            return [base + named_index]

        named_rgb = _NAMED_RGB_COLORS.get(color)
        if named_rgb is not None:
            return [prefix, 2, *named_rgb]

        if fullmatch(r"#[0-9A-Fa-f]{6}", color):
            return [
                prefix,
                2,
                int(color[1:3], 16),
                int(color[3:5], 16),
                int(color[5:7], 16),
            ]
        raise ValueError(f"Unknown or invalid color: {color!r}")

    raise TypeError("A color must be a name, index, RGB tuple, or hexadecimal string")


def style(
    text: str,
    *,
    bold: bool = False,
    dim: bool = False,
    italic: bool = False,
    underline: bool = False,
    strikethrough: bool = False,
    reverse: bool = False,
    foreground: TextColor | None = None,
    background: TextColor | None = None,
) -> str:
    """Apply terminal styles to text and remove unsafe control sequences.

    Safe existing SGR styles and HTTP(S) hyperlinks are preserved, as are
    newlines and tabs. Other terminal commands and control characters are
    removed. Enabled styles are opened before the text and their categories
    reset afterward. Rendering support for colors and effects depends on the
    terminal. Nesting the same category does not restore an outer value after
    an inner reset; combine effects in one call when they must cover the whole
    string. Bold and dim share the terminal's intensity-reset category.

    Args:
        text: String to sanitize and style, possibly containing safe styles.
        bold: Enable bold intensity. Defaults to ``False``.
        dim: Enable dim intensity. Defaults to ``False``.
        italic: Enable italic text. Defaults to ``False``.
        underline: Enable underlining. Defaults to ``False``.
        strikethrough: Enable struck-through text. Defaults to ``False``.
        reverse: Swap foreground and background visually. Defaults to ``False``.
        foreground: Text color, or ``None`` to leave that category unchanged.
            Accepts ``black``, ``red``, ``green``, ``yellow``, ``blue``,
            ``magenta``, ``cyan``, ``white``, their ``bright_`` variants,
            ``orange``, ``gray``, and ``dark_`` variants of red, green, yellow,
            blue, magenta, cyan, orange and gray. Also accepts an integer palette
            index in ``0..255``, a three-integer RGB tuple in ``0..255``, or a
            ``#RRGGBB`` string. Names are case-sensitive.
        background: Cell background color in the same formats as ``foreground``.
            ``None`` leaves that category unchanged.

    Returns:
        Sanitized text wrapped in the requested SGR opening and category-reset
        sequences. Without enabled effects or colors, returns sanitized text
        without adding any sequences. No output is written to the terminal.

    Raises:
        TypeError: If ``text`` is not a string, an effect is not a bool, a color
            has an unsupported type, or an RGB tuple is not exactly three
            integers. Bool is not accepted as a color index or RGB component.
        ValueError: If a color name or hexadecimal string is invalid, or a
            palette index or RGB component is outside ``0..255``.

    Example:
        ``style("Ready", bold=True, foreground="green", background="#102030")``
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    effects = {
        "bold": bold,
        "dim": dim,
        "italic": italic,
        "underline": underline,
        "strikethrough": strikethrough,
        "reverse": reverse,
    }
    for name, enabled in effects.items():
        if not isinstance(enabled, bool):
            raise TypeError(f"{name} must be a boolean")

    safe_text = sanitize_terminal_text(text)
    opening: list[int] = []
    resets: list[int] = []
    for name, code, reset in _STYLE_CODES:
        if effects[name]:
            opening.append(code)
            if reset not in resets:
                resets.append(reset)

    if foreground is not None:
        opening.extend(_color_code(foreground, background=False))
        resets.append(39)
    if background is not None:
        opening.extend(_color_code(background, background=True))
        resets.append(49)

    if not opening:
        return safe_text

    open_sgr = ";".join(str(code) for code in opening)
    reset_sgr = ";".join(str(code) for code in resets)
    return f"\033[{open_sgr}m{safe_text}\033[{reset_sgr}m"


def hyperlink(text: str, url: str) -> str:
    """Wrap safe styled text in a terminal OSC 8 HTTP(S) hyperlink.

    This creates a string without writing it. A compatible terminal makes the
    visible text clickable; terminals without hyperlink support still show the
    text. Existing hyperlinks in ``text`` are removed to prevent nesting.

    Args:
        text: Visible link text. Unsafe terminal controls and nested OSC links
            are removed; safe SGR color and style sequences are retained.
        url: Absolute HTTP or HTTPS URL with a network location. Whitespace,
            C0/C1 controls, Escape, and backslash are rejected.

    Returns:
        Sanitized text enclosed by a complete OSC 8 open/close pair.

    Raises:
        ValueError: If ``url`` is unsafe or is not an absolute HTTP(S) URL.
        TypeError: If ``text`` is not a string.

    Example:
        ``hyperlink("Tuiloom", "https://github.com/maroard/Tuiloom")``
    """
    if not is_safe_hyperlink_url(url):
        raise ValueError(f"Invalid terminal hyperlink URL: {url!r}")
    safe_text = sanitize_hyperlink_text(text)
    return f"\033]8;;{url}\033\\{safe_text}\033]8;;\033\\"
