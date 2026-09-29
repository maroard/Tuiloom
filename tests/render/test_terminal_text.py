import pytest

from tuiloom import hyperlink
from tuiloom.render.terminal_text import (
    RESET_SGR,
    center_display,
    clip_display,
    display_width,
    ljust_display,
    normalize_line,
    normalize_text_lines,
    overlay_display,
    sanitize_hyperlink_text,
    sanitize_terminal_text,
    visual_cells,
    wrap_display,
)


def test_normalize_line_keeps_sgr_and_strips_terminal_controls() -> None:
    text = "\x1b[38;2;10;20;30mcolor\x1b[2J\x1b[4H\x1b]0;title\x07\x1b[0m"

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


def test_normalize_line_keeps_selective_sgr_resets() -> None:
    line = normalize_line("\x1b[1;31mbold red\x1b[22;39mplain")

    assert "\x1b[1;31m" in line
    assert "\x1b[22;39m" in line
    assert display_width(line) == 13


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


def test_right_clip_preserves_style_changes_after_plain_prefix() -> None:
    clipped = clip_display(" \x1b[31mred\x1b[0mplain", 0, 6)
    assert display_width(clipped) == 6
    assert " \x1b[31mred\x1b[0mpl" in clipped
    assert clipped.endswith(RESET_SGR)


def test_offset_clip_preserves_active_style_and_interior_resets() -> None:
    clipped = clip_display("\x1b[31mzero red\x1b[0m plain", 5, 12)
    assert display_width(clipped) == 7
    assert "\x1b[31mred\x1b[0m pla" in clipped
    assert clipped.endswith(RESET_SGR)


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


def test_tab_columns_ignore_style_sequences_inside_a_grapheme() -> None:
    line = normalize_line("a👩\033[31m‍💻b\tX")

    assert "b    X" in line
    assert display_width(line) == 9


def test_visual_cells_keep_grapheme_width_style_and_offsets() -> None:
    cells = visual_cells("\x1b[31mA界\x1b[0m")

    assert [(cell.text, cell.offset, cell.width) for cell in cells] == [
        ("A", 0, 1),
        ("界", 0, 2),
        ("界", 1, 2),
    ]
    assert all("\x1b[31m" in cell.style for cell in cells)


def test_visual_cells_keep_combining_sequence_as_one_cell() -> None:
    cells = visual_cells("e\u0301")

    assert len(cells) == 1
    assert cells[0].text == "e\u0301"


def test_overlay_display_uses_columns_and_blanks_partial_graphemes() -> None:
    assert overlay_display("A界B界D", "xy", 2) == "A xy界D"
    assert overlay_display("A界B界D", "xy", 3) == "A界xy D"
    assert overlay_display("", "👩‍💻e\u0301", 4) == "    👩‍💻e\u0301"


def test_overlay_display_resets_background_style_and_restores_the_suffix() -> None:
    line = overlay_display("\033[31mabcdef\033[0m", "XY", 2)
    assert display_width(line) == 6
    assert "\033[31mab\033[0mXY" in line
    assert "\033[31mef" in line
    assert line.endswith(RESET_SGR)


@pytest.mark.parametrize("sequence", ["\033[>4;2m", "\033[?1m", "\033[31 m"])
def test_sanitizers_reject_private_and_intermediate_csi_m(sequence: str) -> None:
    assert sanitize_terminal_text(sequence + "text") == "text"
    assert sanitize_hyperlink_text(sequence + "text") == "text"


def test_wrap_display_preserves_a_hyperlink_on_every_wrapped_row() -> None:
    lines = wrap_display(hyperlink("abcdef", "https://example.com"), 3)

    assert [display_width(line) for line in lines] == [3, 3]
    assert all("https://example.com\033\\" in line for line in lines)
    assert all("\033]8;;\033\\" in line for line in lines)


def test_normalize_text_lines_reopens_and_closes_hyperlinks_on_each_row() -> None:
    lines = normalize_text_lines(
        hyperlink("\033[31mfirst\nsecond\033[0m", "https://example.com")
    )

    assert len(lines) == 2
    assert all("https://example.com\033\\" in line for line in lines)
    assert all("\033]8;;\033\\" in line for line in lines)
    assert all("\033[31m" in line for line in lines)
    assert all(line.endswith(RESET_SGR) for line in lines)


def test_normalize_line_closes_an_unterminated_safe_hyperlink() -> None:
    line = normalize_line("\033]8;;https://example.com\033\\linked")

    assert line.endswith("\033]8;;\033\\")
