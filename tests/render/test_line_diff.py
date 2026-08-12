from tuiloom.render.line_diff import LineChange, get_line_changes


def test_line_diff_returns_only_changed_lines() -> None:
    assert get_line_changes(
        ["same", "before", "same again"],
        ["same", "after", "same again"],
    ) == [LineChange(row=2, content="after")]


def test_line_diff_returns_added_lines() -> None:
    assert get_line_changes(["first"], ["first", "second"]) == [
        LineChange(row=2, content="second")
    ]


def test_line_diff_clears_removed_trailing_lines() -> None:
    assert get_line_changes(["first", "second"], ["first"]) == [
        LineChange(row=2, content="")
    ]


def test_line_diff_returns_added_empty_trailing_line() -> None:
    assert get_line_changes(["first"], ["first", ""]) == [LineChange(row=2, content="")]


def test_line_diff_clears_removed_empty_trailing_line() -> None:
    assert get_line_changes(["first", ""], ["first"]) == [LineChange(row=2, content="")]
