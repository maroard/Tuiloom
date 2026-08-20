from urllib.parse import urlparse


def hyperlink(text: str, url: str) -> str:
    """Return text linked to one safe HTTP(S) URL with terminal OSC 8."""
    parsed_url = urlparse(url)
    contains_control = any(
        ord(character) < 32 or 127 <= ord(character) <= 159 for character in url
    )

    if (
        parsed_url.scheme not in ("http", "https")
        or not parsed_url.netloc
        or contains_control
    ):
        raise ValueError(f"Invalid terminal hyperlink URL: {url!r}")

    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"
