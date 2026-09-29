from dataclasses import dataclass
from re import compile as compile_pattern
from urllib.parse import urlparse

from wcwidth import center as wc_center
from wcwidth import clip as wc_clip
from wcwidth import iter_graphemes, iter_sequences, propagate_sgr
from wcwidth import ljust as wc_ljust
from wcwidth import width as wc_width
from wcwidth import wrap as wc_wrap

RESET_SGR = "\x1b[0m"
CLOSE_HYPERLINK = "\x1b]8;;\x1b\\"
_SGR_PATTERN = compile_pattern(r"\x1b\[[0-9;:]*m\Z")
# wcwidth adds a shared id when wrapping a link onto several rows.
_HYPERLINK_PATTERN = compile_pattern(
    r"\x1b\]8;(?:id=[A-Za-z0-9._:-]+)?;([^\x1b\\]*)\x1b\\\Z"
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
            hyperlink_match = _HYPERLINK_PATTERN.fullmatch(part)
            if _SGR_PATTERN.fullmatch(part) or (
                hyperlink_match is not None
                and (
                    not hyperlink_match.group(1)
                    or is_safe_hyperlink_url(hyperlink_match.group(1))
                )
            ):
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


def is_safe_hyperlink_url(url: str) -> bool:
    """Return whether an URL is safe for an OSC 8 parameter."""
    if not isinstance(url, str) or not url or "\\" in url:
        return False
    if any(
        character.isspace() or ord(character) < 32 or 127 <= ord(character) <= 159
        for character in url
    ):
        return False
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(netloc)


def sanitize_hyperlink_text(text: str) -> str:
    """Keep printable text and safe SGR while removing every OSC sequence."""
    safe_parts: list[str] = []
    for part, is_sequence in iter_sequences(text):
        if is_sequence:
            if _SGR_PATTERN.fullmatch(part):
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
    """Measure one safe text line in terminal cells, retaining Unicode graphemes.

    Safe SGR and hyperlink sequences occupy no cells. Tabs advance to the next
    eight-cell stop from column zero. This is not a multiline layout function;
    split lines first to compute a maximum width. Unsafe controls are removed.

    Args:
        text: One terminal text line, possibly containing safe SGR styles, OSC 8
            HTTP(S) hyperlinks, tabs, wide characters or combining graphemes.
            Split multiline text before calling this function; a newline does
            not produce an independent line-width result.

    Returns:
        Visible cell count after sanitization, starting at column zero. Empty
        text has width zero; styles and hyperlink controls contribute no cells.
        This is a terminal width, not a character or UTF-8 byte count.

    Raises:
        TypeError: If ``text`` is not a string.
    """
    return wc_width(sanitize_terminal_text(text), tabsize=8)


def _finish_terminal_line(line: str) -> str:
    """Close a hyperlink and reset SGR before leaving a physical line."""
    has_sgr = any(
        is_sequence and _SGR_PATTERN.fullmatch(part)
        for part, is_sequence in iter_sequences(line)
    )
    if hyperlink_continuation(line):
        line += CLOSE_HYPERLINK
    return line + RESET_SGR if has_sgr and not line.endswith(RESET_SGR) else line


def hyperlink_continuation(text: str, prefix: str = "") -> str:
    """Return the last active OSC 8 opening in already sanitized text."""
    for part, is_sequence in iter_sequences(text):
        if is_sequence and (match := _HYPERLINK_PATTERN.fullmatch(part)):
            prefix = part if match.group(1) else ""
    return prefix


def sgr_continuation(text: str, prefix: str = "") -> str:
    """Return the SGR prefix needed after already sanitized text."""
    continuation = propagate_sgr([prefix + text, ""])[1]
    return continuation.removesuffix(RESET_SGR)


def expand_tabs(text: str, column: int = 0) -> str:
    """Expand tabs from a terminal column without rewriting style sequences."""
    if "\t" not in text:
        return text
    parts = text.split("\t")
    expanded = [parts[0]]
    column += max(0, wc_width(parts[0]))
    for part in parts[1:]:
        spaces = 8 - column % 8
        expanded.extend([" " * spaces, part])
        column += spaces + max(0, wc_width(part))
    return "".join(expanded)


def normalize_line(text: str) -> str:
    """Return one safe line with expanded tabs and closed terminal styles."""
    safe = sanitize_terminal_text(text).replace("\n", "")
    expanded = expand_tabs(safe)
    return _finish_terminal_line(expanded)


def normalize_text_lines(text: str) -> list[str]:
    """Normalize text and carry SGR and hyperlinks across newline boundaries."""
    safe = sanitize_terminal_text(text)
    raw_lines = safe.splitlines() or [""]
    lines: list[str] = []
    hyperlink = ""
    sgr = ""
    for raw_line in raw_lines:
        line = hyperlink + sgr + raw_line
        lines.append(normalize_line(line))
        hyperlink = hyperlink_continuation(raw_line, hyperlink)
        sgr = sgr_continuation(raw_line, sgr)
    return lines


def clip_display(text: str, start: int, end: int) -> str:
    """Clip safe text at terminal-column boundaries."""
    return normalize_line(
        wc_clip(
            sanitize_terminal_text(text),
            start,
            end,
            tabsize=8,
            # Retain literal SGR, including the state preceding the clip.
            # Propagation can collapse in-range transitions to the first style.
            propagate_sgr=False,
        )
    )


def ljust_display(text: str, width: int) -> str:
    """Pad safe text on the right to a visible terminal width."""
    return normalize_line(wc_ljust(sanitize_terminal_text(text), width))


def center_display(text: str, width: int) -> str:
    """Center safe text within a visible terminal width."""
    return normalize_line(wc_center(sanitize_terminal_text(text), width))


def overlay_display(background: str, foreground: str, column: int) -> str:
    """Replace display cells with an opaque line, retaining both styled edges.

    Clipping pads any partially covered wide grapheme with a space. Each
    fragment closes its styles before the next fragment begins.
    """
    end = column + display_width(foreground)
    prefix = ljust_display(clip_display(background, 0, column), column)
    suffix = clip_display(background, end, max(end, display_width(background)))
    return normalize_line(prefix + normalize_line(foreground) + suffix)


def wrap_display(text: str, width: int, *, drop_whitespace: bool = True) -> list[str]:
    """Wrap safe text without splitting ANSI or Unicode graphemes."""
    safe = sanitize_terminal_text(text)
    wrapped = wc_wrap(
        safe, width, tabsize=8, propagate_sgr=True, drop_whitespace=drop_whitespace
    )
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
