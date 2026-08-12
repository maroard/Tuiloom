from tuiloom.render.terminal_text import (
    RESET_SGR,
    center_display,
    clip_display,
    display_width,
    ljust_display,
    normalize_line,
    normalize_text_lines,
    wrap_display,
)


def test_normalize_line_keeps_sgr_and_strips_terminal_controls() -> None:
    text = (
        "\x1b[38;2;10;20;30mcolor"
        "\x1b[2J\x1b[4H"
        "\x1b]0;title\x07"
        "\x1b[0m"
    )

    line = normalize_line(text)

    assert "\x1b[38;2;10;20;30m" in line
    assert "\x1b[0m" in line
    assert "\x1b[2J" not in line
    assert "\x1b[4H" not in line
    assert "\x1b]0;title\x07" not in line
    assert display_width(line) == 5


def test_normalize_line_keeps_colon_form_sgr() -> None:
    line = normalize_line("\x1b[38:2::10:20:30mRGB\x1b[0m")

    assert "\x1b[38:2::10:20:30m" in line
    assert display_width(line) == 3


def test_normalize_text_lines_propagates_style_and_resets_each_line() -> None:
    lines = normalize_text_lines("\x1b[31mfirst\nsecond\x1b[0m")

    assert lines[0].startswith("\x1b[31m")
    assert lines[0].endswith(RESET_SGR)
    assert lines[1].startswith("\x1b[31m")
    assert lines[1].endswith(RESET_SGR)


def test_normalize_line_removes_unsafe_c0_and_c1_controls() -> None:
    assert normalize_line("a\x00\x07\x7fb") == "ab"


def test_display_width_counts_unicode_graphemes_in_terminal_cells() -> None:
    assert display_width("e\u0301") == 1
    assert display_width("界") == 2
    assert display_width("👨‍👩‍👧") == 2
    assert display_width("🇫🇷") == 2


def test_clip_display_never_returns_half_a_wide_grapheme() -> None:
    assert clip_display("A界B", 0, 2) == "A "
    assert clip_display("A界B", 1, 4) == "界B"


def test_padding_and_centering_use_visible_width() -> None:
    styled = "\x1b[31m界\x1b[0m"

    assert display_width(ljust_display(styled, 4)) == 4
    assert display_width(center_display(styled, 4)) == 4
    assert "\x1b[31m" in center_display(styled, 4)


def test_wrap_display_preserves_style_and_visible_width() -> None:
    lines = wrap_display("\x1b[32m界界界\x1b[0m", 4)

    assert [display_width(line) for line in lines] == [4, 2]
    assert all("\x1b[32m" in line for line in lines)


def test_normalize_line_expands_tabs_by_terminal_columns() -> None:
    assert normalize_line("界\tb") == "界      b"
