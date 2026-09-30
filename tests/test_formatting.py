import pytest

from tuiloom import align_left, align_right, center, columns, hyperlink, line, style
from tuiloom.render.terminal_text import display_width, sanitize_terminal_text


def test_text_alignment_and_line_use_display_cells() -> None:
    assert line(4) == "────"
    assert line(3, char="e\u0301") == "e\u0301" * 3
    assert align_left("界", 4) == "界  "
    assert align_right("界", 4) == "  界"
    assert center("界", 5) == "  界 "
    assert align_left("abcdef", 3) == "abc"
    assert align_right("abcdef", 3) == "abc"
    assert center("abcdef", 3) == "abc"
    assert all(
        display_width(value) == 4
        for value in (line(4), align_left("界", 4), align_right("界", 4))
    )


def test_helpers_keep_ansi_and_wide_graphemes_at_exact_width() -> None:
    styled = "\x1b[31m👨‍👩‍👧\x1b[0m"
    for helper in (align_left, align_right, center):
        result = helper(styled, 6)
        assert display_width(result) == 6
        assert "\x1b[31m" in result and "\x1b[0m" in result
    assert display_width(line(2, char="\x1b[31mx\x1b[0m")) == 2


def test_columns_distributes_space_and_clips_overflow() -> None:
    assert columns(["left", "right"], width=16) == "left       right"
    assert columns(["A", "B", "C"], width=9) == "A   B   C"
    assert columns(["abcdefgh", "XYZ"], width=7) == "abc XYZ"
    assert columns(["界", "\x1b[32mgreen\x1b[0m"], width=12).endswith(
        "\x1b[32mgreen\x1b[0m"
    )
    assert display_width(columns(["界", "green"], width=12)) == 12
    assert columns(["A", "B"], width=0) == ""


@pytest.mark.parametrize("width", [-1, True, 1.5])
def test_helpers_reject_invalid_width(width: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        line(width)  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError)):
        center("x", width)  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError)):
        columns(["a", "b"], width=width)  # type: ignore[arg-type]


def test_line_rejects_wide_or_empty_repeat_character() -> None:
    for char in ("", "界", "ab"):
        with pytest.raises(ValueError):
            line(3, char=char)


@pytest.mark.parametrize(
    ("option", "opening", "reset"),
    [
        ("bold", 1, 22),
        ("dim", 2, 22),
        ("italic", 3, 23),
        ("underline", 4, 24),
        ("strikethrough", 9, 29),
        ("reverse", 7, 27),
    ],
)
def test_style_applies_each_effect(option: str, opening: int, reset: int) -> None:
    assert style("text", **{option: True}) == (f"\x1b[{opening}mtext\x1b[{reset}m")


def test_style_combines_effects_colors_and_targeted_resets() -> None:
    assert (
        style(
            "text",
            bold=True,
            dim=True,
            italic=True,
            underline=True,
            strikethrough=True,
            reverse=True,
            foreground="red",
            background="bright_blue",
        )
        == "\x1b[1;2;3;4;9;7;31;104mtext\x1b[22;23;24;29;27;39;49m"
    )


@pytest.mark.parametrize(
    ("color", "foreground", "background"),
    [
        ("black", "30", "40"),
        ("red", "31", "41"),
        ("green", "32", "42"),
        ("yellow", "33", "43"),
        ("blue", "34", "44"),
        ("magenta", "35", "45"),
        ("cyan", "36", "46"),
        ("white", "37", "47"),
        ("bright_black", "90", "100"),
        ("bright_red", "91", "101"),
        ("bright_green", "92", "102"),
        ("bright_yellow", "93", "103"),
        ("bright_blue", "94", "104"),
        ("bright_magenta", "95", "105"),
        ("bright_cyan", "96", "106"),
        ("bright_white", "97", "107"),
        ("orange", "38;2;255;165;0", "48;2;255;165;0"),
        ("brown", "38;2;165;42;42", "48;2;165;42;42"),
        ("crimson", "38;2;220;20;60", "48;2;220;20;60"),
        ("darkred", "38;2;139;0;0", "48;2;139;0;0"),
        ("gold", "38;2;255;215;0", "48;2;255;215;0"),
        ("lime", "38;2;0;255;0", "48;2;0;255;0"),
        ("maroon", "38;2;128;0;0", "48;2;128;0;0"),
        ("purple", "38;2;128;0;128", "48;2;128;0;128"),
        ("violet", "38;2;238;130;238", "48;2;238;130;238"),
        ("gray", "38;2;128;128;128", "48;2;128;128;128"),
        ("dark_red", "38;2;127;0;0", "48;2;127;0;0"),
        ("dark_green", "38;2;0;127;0", "48;2;0;127;0"),
        ("dark_yellow", "38;2;127;127;0", "48;2;127;127;0"),
        ("dark_blue", "38;2;0;0;127", "48;2;0;0;127"),
        ("dark_magenta", "38;2;127;0;127", "48;2;127;0;127"),
        ("dark_cyan", "38;2;0;127;127", "48;2;0;127;127"),
        ("dark_orange", "38;2;127;82;0", "48;2;127;82;0"),
        ("dark_gray", "38;2;64;64;64", "48;2;64;64;64"),
        (0, "38;5;0", "48;5;0"),
        (255, "38;5;255", "48;5;255"),
        ((0, 127, 255), "38;2;0;127;255", "48;2;0;127;255"),
        ("#00A0ff", "38;2;0;160;255", "48;2;0;160;255"),
    ],
)
def test_style_accepts_all_color_representations(
    color: str | int | tuple[int, int, int],
    foreground: str,
    background: str,
) -> None:
    assert style("x", foreground=color) == f"\x1b[{foreground}mx\x1b[39m"
    assert style("x", background=color) == f"\x1b[{background}mx\x1b[49m"


@pytest.mark.parametrize(
    "option", ["bold", "dim", "italic", "underline", "strikethrough", "reverse"]
)
@pytest.mark.parametrize("value", [1, 0, None, "yes", object()])
def test_style_rejects_non_boolean_effect_flags(option: str, value: object) -> None:
    with pytest.raises(TypeError, match=f"{option} must be a boolean"):
        style("x", **{option: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "color",
    [True, False, 1.5, object(), (1, 2), (1, 2, 3, 4), (1, "2", 3), (1, True, 3)],
)
@pytest.mark.parametrize("option", ["foreground", "background"])
def test_style_rejects_invalid_color_types_and_rgb_shapes(
    color: object, option: str
) -> None:
    with pytest.raises(TypeError):
        style("x", **{option: color})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "color",
    [-1, 256, (0, -1, 0), (0, 256, 0), "unknown", "RED", "#123", "#GG0000"],
)
@pytest.mark.parametrize("option", ["foreground", "background"])
def test_style_rejects_invalid_color_values(color: object, option: str) -> None:
    with pytest.raises(ValueError):
        style("x", **{option: color})  # type: ignore[arg-type]


def test_style_sanitizes_text_and_preserves_safe_sgr_and_hyperlinks() -> None:
    link = hyperlink("\x1b[3mlink\x1b[23m", "https://example.com")
    result = style(f"\x1b[2J\x00{link}\x7f", underline=True)
    assert result == f"\x1b[4m{link}\x1b[24m"
    assert sanitize_terminal_text(result) == result


def test_hyperlink_preserves_text_styled_before_wrapping() -> None:
    styled = style("link", bold=True, foreground="cyan")
    result = hyperlink(styled, "https://example.com")
    assert styled in result
    assert sanitize_terminal_text(result) == result


def test_style_without_options_only_sanitizes_text() -> None:
    assert style("hé🙂\nline\x00\x1b[31mred\x1b[0m") == ("hé🙂\nline\x1b[31mred\x1b[0m")


def test_style_does_not_change_unicode_multiline_display_width() -> None:
    text = "hé🙂\n界"
    styled = style(text, bold=True, foreground=(10, 20, 30), background=240)
    assert display_width(styled) == display_width(text)


def test_style_rejects_non_string_text() -> None:
    with pytest.raises(TypeError, match="text must be a string"):
        style(42)  # type: ignore[arg-type]


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
