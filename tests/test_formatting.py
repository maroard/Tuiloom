import pytest

from tuiloom import hyperlink
from tuiloom.render.terminal_text import sanitize_terminal_text


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "https:///missing-host",
        "https://example.com/a b",
        "https://example.com/a\\b",
        "https://example.com/\x1b]8;;evil",
        "https://example.com/\x7f",
        "https://example.com/\x85",
        "https://[broken",
    ],
)
def test_hyperlink_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError, match="Invalid terminal hyperlink URL"):
        hyperlink("link", url)


def test_hyperlink_accepts_http_https_and_sanitizes_text() -> None:
    result = hyperlink(
        "\x1b[31mred\x1b[0m\x1b[2J\x1b]8;;https://evil.test\x1b\\nested",
        "https://example.com/a?b=1#c",
    )
    assert result.startswith("\x1b]8;;https://example.com/a?b=1#c\x1b\\")
    assert result.endswith("\x1b]8;;\x1b\\")
    assert "\x1b[31m" in result
    assert "\x1b[2J" not in result
    assert "evil.test" not in result
    assert sanitize_terminal_text(result) == result


def test_sanitizer_revalidates_hyperlink_sequences_and_removes_orphan_osc() -> None:
    safe = hyperlink("safe", "http://example.com")
    unsafe = "\x1b]8;;file:///tmp/x\x1b\\bad\x1b]8;;\x1b\\"
    assert sanitize_terminal_text(safe) == safe
    sanitized = sanitize_terminal_text(unsafe)
    assert "file:///" not in sanitized
    assert sanitized == "bad\x1b]8;;\x1b\\"
