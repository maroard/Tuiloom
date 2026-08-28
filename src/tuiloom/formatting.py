from tuiloom.render.terminal_text import (
    is_safe_hyperlink_url,
    sanitize_hyperlink_text,
)


def hyperlink(text: str, url: str) -> str:
    """Wrap safe styled text in a terminal OSC 8 HTTP(S) hyperlink.

    Args:
        text: Visible link text. Unsafe terminal controls and nested OSC links
            are removed; safe SGR color and style sequences are retained.
        url: Absolute HTTP or HTTPS URL with a network location. Whitespace,
            C0/C1 controls, Escape, and backslash are rejected.

    Returns:
        Sanitized text enclosed by a complete OSC 8 open/close pair.

    Raises:
        ValueError: If ``url`` is unsafe or is not an absolute HTTP(S) URL.

    Example:
        ``hyperlink("Tuiloom", "https://github.com/maroard/Tuiloom")``
    """
    if not is_safe_hyperlink_url(url):
        raise ValueError(f"Invalid terminal hyperlink URL: {url!r}")
    safe_text = sanitize_hyperlink_text(text)
    return f"\033]8;;{url}\033\\{safe_text}\033]8;;\033\\"
