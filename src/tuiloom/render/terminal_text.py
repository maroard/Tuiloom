from dataclasses import dataclass
from re import compile as compile_pattern

from wcwidth import center as wc_center
from wcwidth import clip as wc_clip
from wcwidth import iter_graphemes, iter_sequences, propagate_sgr
from wcwidth import ljust as wc_ljust
from wcwidth import width as wc_width
from wcwidth import wrap as wc_wrap

RESET_SGR = "\x1b[0m"
_SGR_PATTERN = compile_pattern(r"\x1b\[[0-?]*[ -/]*m\Z")
_HYPERLINK_PATTERN = compile_pattern(
    r"\x1b\]8;;(?:https?://[^\x00-\x20\x7f-\x9f\x1b\\]+)?\x1b\\\Z"
)


@dataclass(frozen=True)
class VisualCell:
    """Identify one occupied column of a styled Unicode grapheme."""

    text: str
    style: str
    offset: int
    width: int


def sanitize_terminal_text(text: str) -> str:
    """Keep printable text, SGR styles, and safe HTTP(S) hyperlinks."""
    safe_parts: list[str] = []

    for part, is_sequence in iter_sequences(text):
        if is_sequence:
            if _SGR_PATTERN.fullmatch(part) or _HYPERLINK_PATTERN.fullmatch(part):
                safe_parts.append(part)
            continue

        safe_parts.append(
            "".join(
                character
                for character in part
                if character in "\n\t"
                or (ord(character) >= 32 and not 127 <= ord(character) <= 159)
            )
        )

    return "".join(safe_parts)


def display_width(text: str) -> int:
    """Return the number of terminal cells occupied by safe text."""
    return wc_width(sanitize_terminal_text(text), tabsize=8)


def _finish_sgr_line(line: str) -> str:
    """Reset a line that contains style sequences."""
    has_sgr = any(is_sequence for _, is_sequence in iter_sequences(line))
    return line + RESET_SGR if has_sgr and not line.endswith(RESET_SGR) else line


def _expand_tabs(text: str) -> str:
    """Expand tabs without rewriting embedded SGR sequences."""
    expanded: list[str] = []
    column = 0

    for part, is_sequence in iter_sequences(text):
        if is_sequence:
            expanded.append(part)
            continue

        for grapheme in iter_graphemes(part):
            if grapheme == "\t":
                spaces = 8 - column % 8
                expanded.append(" " * spaces)
                column += spaces
                continue

            expanded.append(grapheme)
            column += max(0, wc_width(grapheme))

    return "".join(expanded)


def normalize_line(text: str) -> str:
    """Return one safe line with expanded tabs and a closed SGR state."""
    safe = sanitize_terminal_text(text).replace("\n", "")
    expanded = _expand_tabs(safe)
    return _finish_sgr_line(expanded)


def normalize_text_lines(text: str) -> list[str]:
    """Normalize text and propagate SGR state across newline boundaries."""
    safe = sanitize_terminal_text(text)
    raw_lines = safe.splitlines() or [""]
    return [normalize_line(line) for line in propagate_sgr(raw_lines)]


def clip_display(text: str, start: int, end: int) -> str:
    """Clip safe text at terminal-column boundaries."""
    return normalize_line(
        wc_clip(
            sanitize_terminal_text(text),
            start,
            end,
            tabsize=8,
            propagate_sgr=True,
        )
    )


def ljust_display(text: str, width: int) -> str:
    """Pad safe text on the right to a visible terminal width."""
    return normalize_line(wc_ljust(sanitize_terminal_text(text), width))


def center_display(text: str, width: int) -> str:
    """Center safe text within a visible terminal width."""
    return normalize_line(wc_center(sanitize_terminal_text(text), width))


def wrap_display(text: str, width: int) -> list[str]:
    """Wrap safe text without splitting ANSI or Unicode graphemes."""
    safe = sanitize_terminal_text(text)
    wrapped = wc_wrap(safe, width, tabsize=8, propagate_sgr=True)
    return [normalize_line(line) for line in wrapped] or [""]


def visual_cells(text: str) -> list[VisualCell]:
    """Project safe styled graphemes into comparable terminal cells."""
    safe = normalize_line(text)
    plain_characters: list[str] = []
    styles: list[str] = []
    style = ""

    for part, is_sequence in iter_sequences(safe):
        if is_sequence:
            style += part
            continue

        plain_characters.extend(part)
        styles.extend([style] * len(part))

    plain = "".join(plain_characters)
    cells: list[VisualCell] = []
    index = 0

    for grapheme in iter_graphemes(plain):
        grapheme_width = wc_width(grapheme)
        grapheme_style = styles[index] if index < len(styles) else ""
        index += len(grapheme)

        if grapheme_width <= 0:
            continue

        cells.extend(
            VisualCell(grapheme, grapheme_style, offset, grapheme_width)
            for offset in range(grapheme_width)
        )

    return cells
