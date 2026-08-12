from tuiloom.render.segment_diff import SegmentChange, get_segment_changes
from tuiloom.render.terminal_text import RESET_SGR, display_width


def contents(changes: list[SegmentChange]) -> list[str]:
    return [change.content for change in changes]


def test_segment_diff_returns_two_disjoint_changes() -> None:
    changes = get_segment_changes(
        ["abc DEF ghi JKL"],
        ["abc XYZ ghi MNO"],
    )

    assert [(change.row, change.column) for change in changes] == [
        (1, 5),
        (1, 13),
    ]
    assert [display_width(value) for value in contents(changes)] == [3, 3]
    assert "XYZ" in changes[0].content
    assert "MNO" in changes[1].content


def test_segment_diff_detects_style_only_change() -> None:
    changes = get_segment_changes(
        ["\x1b[31mred\x1b[0m"],
        ["\x1b[32mred\x1b[0m"],
    )

    assert len(changes) == 1
    assert changes[0].column == 1
    assert "\x1b[32m" in changes[0].content
    assert changes[0].content.startswith(RESET_SGR)
    assert changes[0].content.endswith(RESET_SGR)


def test_segment_diff_clears_removed_trailing_cells() -> None:
    assert get_segment_changes(["abcdef"], ["abc"]) == [
        SegmentChange(
            row=1,
            column=4,
            content=RESET_SGR + RESET_SGR,
            clear_width=3,
        )
    ]


def test_segment_diff_expands_wide_grapheme_change() -> None:
    changes = get_segment_changes(["A界B"], ["A🙂B"])

    assert len(changes) == 1
    assert changes[0].column == 2
    assert display_width(changes[0].content) == 2


def test_segment_diff_handles_added_removed_and_empty_rows() -> None:
    added = get_segment_changes(["first"], ["first", "界"])
    removed = get_segment_changes(["first", "界"], ["first"])
    empty_added = get_segment_changes(["first"], ["first", ""])
    empty_removed = get_segment_changes(["first", ""], ["first"])

    assert (added[0].row, added[0].column) == (2, 1)
    assert removed[0].clear_width == 2
    marker = SegmentChange(
        row=2,
        column=1,
        content=RESET_SGR + RESET_SGR,
    )
    assert empty_added == [marker]
    assert empty_removed == [marker]


def test_segment_diff_ignores_identical_lines() -> None:
    assert get_segment_changes(["same"], ["same"]) == []
