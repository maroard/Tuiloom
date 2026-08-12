# Segment Differential Rendering and ANSI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render every Tuiloom visual element with safe ANSI SGR and correct Unicode geometry, then update multiple changed segments instead of replacing complete terminal lines.

**Architecture:** A new `terminal_text` module owns sanitization and display-cell geometry for the whole library. A visual-cell segment diff analyzes only changed lines and returns self-contained terminal updates consumed by the existing `TerminalRenderer`.

**Tech Stack:** Python 3.12, `wcwidth >= 0.8`, pytest, mypy strict, Ruff

---

## File Structure

- Create `src/tuiloom/render/terminal_text.py`: safe SGR filtering, Unicode graphemes, terminal width, clipping, padding, centering, wrapping, and styled visual cells.
- Create `tests/render/test_terminal_text.py`: focused safety and Unicode geometry tests.
- Modify `src/tuiloom/render/content_renderer.py`: normalize source lines and dimensions through terminal text primitives.
- Modify `src/tuiloom/render/viewport.py`: clip, pad, and scroll by terminal columns.
- Modify `tests/render/test_content_renderer.py` and `tests/render/test_viewport.py`: styled Unicode renderer coverage.
- Create `src/tuiloom/render/segment_diff.py`: positional visual-cell diff and `SegmentChange`.
- Create `tests/render/test_segment_diff.py`: segment grouping, style, Unicode, and row lifecycle tests.
- Delete `src/tuiloom/render/line_diff.py` and `tests/render/test_line_diff.py` after all imports move to the segment API.
- Modify `src/tuiloom/render/terminal_renderer.py`: compose safe frames, write segments, and restore the cursor by visible width.
- Modify `tests/render/test_terminal_renderer.py`: exact differential ANSI writes and safety boundary tests.
- Modify `src/tuiloom/render/menu_renderer.py`: use terminal-aware measurement and alignment for every screen field.
- Modify `tests/render/test_menu_renderer.py`: ANSI and Unicode coverage for every menu region.
- Modify `pyproject.toml`: add the sole runtime dependency.
- Modify `README.md`: document safe ANSI/Unicode behavior and its intentional control-sequence restriction.

### Task 1: Add safe terminal text primitives

**Files:**
- Modify: `pyproject.toml`
- Create: `src/tuiloom/render/terminal_text.py`
- Create: `tests/render/test_terminal_text.py`

- [ ] **Step 1: Add the runtime dependency**

Change the project dependency list to:

```toml
dependencies = [
    "wcwidth>=0.8",
]
```

Run: `uv sync`

Expected: dependency resolution succeeds and `uv run python -c "import wcwidth; print(wcwidth.__version__)"` reports version `0.8` or newer.

- [ ] **Step 2: Write failing sanitization and line-normalization tests**

Create `tests/render/test_terminal_text.py` with:

```python
from tuiloom.render.terminal_text import (
    RESET_SGR,
    display_width,
    normalize_line,
    normalize_text_lines,
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
```

- [ ] **Step 3: Run the safety tests and verify RED**

Run: `uv run pytest -q tests/render/test_terminal_text.py`

Expected: collection fails because `tuiloom.render.terminal_text` does not exist.

- [ ] **Step 4: Implement filtering and independently renderable lines**

Create `src/tuiloom/render/terminal_text.py` with these public internal primitives:

```python
from dataclasses import dataclass
from re import compile as compile_pattern

from wcwidth import (
    center as wc_center,
    clip as wc_clip,
    iter_graphemes,
    iter_sequences,
    ljust as wc_ljust,
    propagate_sgr,
    width as wc_width,
    wrap as wc_wrap,
)

RESET_SGR = "\x1b[0m"
_SGR_PATTERN = compile_pattern(r"\x1b\[[0-?]*[ -/]*m\Z")


def sanitize_terminal_text(text: str) -> str:
    """Keep printable text, newlines, tabs, and SGR style sequences."""
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
                or ord(character) >= 32
                and not 127 <= ord(character) <= 159
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


def normalize_line(text: str) -> str:
    """Return one safe line with expanded tabs and a closed SGR state."""
    safe = sanitize_terminal_text(text).replace("\n", "")
    expanded = wc_clip(safe, 0, wc_width(safe, tabsize=8), tabsize=8)
    return _finish_sgr_line(expanded)


def normalize_text_lines(text: str) -> list[str]:
    """Normalize text and propagate SGR state across newline boundaries."""
    safe = sanitize_terminal_text(text)
    raw_lines = safe.splitlines() or [""]
    return [normalize_line(line) for line in propagate_sgr(raw_lines)]
```

Use explicit parentheses around the printable-character predicate if Ruff requests them. Do not allow `\r`, backspace, ESC, or other C0/C1 values through the plain-text branch.

- [ ] **Step 5: Run the safety tests and verify GREEN**

Run: `uv run pytest -q tests/render/test_terminal_text.py`

Expected: all four tests pass.

- [ ] **Step 6: Write failing Unicode geometry tests**

Append:

```python
from tuiloom.render.terminal_text import (
    center_display,
    clip_display,
    ljust_display,
    wrap_display,
)


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
```

- [ ] **Step 7: Run the geometry tests and verify RED**

Run: `uv run pytest -q tests/render/test_terminal_text.py`

Expected: collection fails because the display helper functions are missing.

- [ ] **Step 8: Add the display helpers**

Add:

```python
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
```

- [ ] **Step 9: Run all terminal-text tests and commit**

Run: `uv run pytest -q tests/render/test_terminal_text.py`

Expected: all terminal-text tests pass.

Run: `uv run mypy src/tuiloom/render/terminal_text.py tests/render/test_terminal_text.py && uv run ruff check src/tuiloom/render/terminal_text.py tests/render/test_terminal_text.py`

Expected: both commands pass.

Commit only this task:

```bash
git add pyproject.toml src/tuiloom/render/terminal_text.py
git add -f tests/render/test_terminal_text.py
git commit -m "feat: add safe ANSI terminal text geometry"
```

### Task 2: Make content and viewport geometry ANSI-aware

**Files:**
- Modify: `src/tuiloom/render/content_renderer.py`
- Modify: `src/tuiloom/render/viewport.py`
- Modify: `tests/render/test_content_renderer.py`
- Modify: `tests/render/test_viewport.py`

- [ ] **Step 1: Add failing ContentRenderer tests**

Append to `tests/render/test_content_renderer.py`:

```python
def test_content_dimensions_use_visible_width_and_safe_ansi() -> None:
    renderer = ContentRenderer("\x1b[31m界\x1b[0m\x1b[2J\ne\u0301")

    content = renderer.update()

    assert content.width == 2
    assert "\x1b[31m" in content.lines[0]
    assert "\x1b[2J" not in content.lines[0]


def test_streamed_style_is_propagated_across_lines() -> None:
    renderer = ContentRenderer(iter(["\x1b[35mfirst", "\nsecond"]))

    renderer.update()
    content = renderer.update()

    assert content.lines[1].startswith("\x1b[35m")
```

- [ ] **Step 2: Run the ContentRenderer tests and verify RED**

Run: `uv run pytest -q tests/render/test_content_renderer.py`

Expected: width is calculated from Python codepoints and unsafe ANSI remains.

- [ ] **Step 3: Normalize content through terminal_text**

Import `display_width`, `normalize_line`, and `normalize_text_lines`. Replace the line assignment and dimension calculation inside `_normalize_content()` with:

```python
if isinstance(content, str):
    self.rendered_content.lines = normalize_text_lines(content)

elif isinstance(content, list) and all(
    isinstance(element, str) for element in content
):
    self.rendered_content.lines = [normalize_line(line) for line in content] or [""]

else:
    raise TypeError(
        f"Content must be str or list[str], got {type(content).__name__}"
    )

self.rendered_content.width = max(
    display_width(line) for line in self.rendered_content.lines
)
self.rendered_content.height = len(self.rendered_content.lines)
```

- [ ] **Step 4: Verify ContentRenderer GREEN**

Run: `uv run pytest -q tests/render/test_content_renderer.py`

Expected: all tests pass.

- [ ] **Step 5: Add failing Viewport tests**

Append to `tests/render/test_viewport.py`:

```python
def test_viewport_clips_and_pads_styled_wide_text_by_columns() -> None:
    rendered = RenderedContent(
        lines=["\x1b[31mA界B\x1b[0m"],
        width=4,
        height=1,
        finished=True,
    )
    viewport = Viewport(rendered, width=3, height=1)

    assert display_width(viewport.render()) == 3
    assert "\x1b[31m" in viewport.render()


def test_horizontal_scroll_does_not_split_wide_grapheme() -> None:
    rendered = RenderedContent(
        lines=["A界B"], width=4, height=1, finished=True
    )
    viewport = Viewport(rendered, width=2, height=1)
    viewport.scroll_right()

    assert viewport.render() == "界"
    assert display_width(viewport.render()) == 2
```

Add `from tuiloom.render.terminal_text import display_width` to the imports.

- [ ] **Step 6: Run the Viewport tests and verify RED**

Run: `uv run pytest -q tests/render/test_viewport.py`

Expected: ordinary string slicing splits or mismeasures the styled wide line.

- [ ] **Step 7: Replace codepoint slicing and padding**

Import `clip_display` and `ljust_display`. Replace the body of the visible-line loop with:

```python
for line in visible_lines:
    visible_part = clip_display(
        line,
        self.offset_x,
        self.offset_x + self.width,
    )
    rendered_lines.append(ljust_display(visible_part, self.width))
```

Keep blank-row padding as ordinary spaces because those lines contain no user content.

- [ ] **Step 8: Verify and commit content geometry**

Run: `uv run pytest -q tests/render/test_content_renderer.py tests/render/test_viewport.py`

Expected: all tests pass.

Commit:

```bash
git add src/tuiloom/render/content_renderer.py src/tuiloom/render/viewport.py
git add -f tests/render/test_content_renderer.py tests/render/test_viewport.py
git commit -m "feat: render content by terminal columns"
```

### Task 3: Build the styled visual-cell segment diff

**Files:**
- Modify: `src/tuiloom/render/terminal_text.py`
- Modify: `tests/render/test_terminal_text.py`
- Create: `src/tuiloom/render/segment_diff.py`
- Create: `tests/render/test_segment_diff.py`

- [ ] **Step 1: Add failing visual-cell tests**

Append to `tests/render/test_terminal_text.py`:

```python
from tuiloom.render.terminal_text import visual_cells


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
```

- [ ] **Step 2: Run the visual-cell tests and verify RED**

Run: `uv run pytest -q tests/render/test_terminal_text.py -k visual_cells`

Expected: import fails because `visual_cells` does not exist.

- [ ] **Step 3: Implement immutable visual cells**

Add to `terminal_text.py`:

```python
@dataclass(frozen=True)
class VisualCell:
    """Identify one occupied column of a styled Unicode grapheme."""

    text: str
    style: str
    offset: int
    width: int


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
```

- [ ] **Step 4: Verify visual cells GREEN**

Run: `uv run pytest -q tests/render/test_terminal_text.py`

Expected: all terminal-text tests pass.

- [ ] **Step 5: Write complete failing segment-diff tests**

Create `tests/render/test_segment_diff.py`:

```python
from tuiloom.render.segment_diff import SegmentChange, get_segment_changes
from tuiloom.render.terminal_text import RESET_SGR, display_width


def contents(changes: list[SegmentChange]) -> list[str]:
    return [change.content for change in changes]


def test_segment_diff_returns_two_disjoint_changes() -> None:
    changes = get_segment_changes(
        ["abc DEF ghi JKL"],
        ["abc XYZ ghi MNO"],
    )

    assert [(change.row, change.column) for change in changes] == [(1, 5), (1, 13)]
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
```

An added or removed empty row deliberately produces a zero-width structural
marker. It emits no visible text but prevents `TerminalRenderer` from treating
the frame as unchanged, so the frame cache and input cursor row are updated.

- [ ] **Step 6: Run segment tests and verify RED**

Run: `uv run pytest -q tests/render/test_segment_diff.py`

Expected: collection fails because `segment_diff` does not exist.

- [ ] **Step 7: Implement positional changed-span grouping**

Create `src/tuiloom/render/segment_diff.py`:

```python
from dataclasses import dataclass
from itertools import zip_longest

from tuiloom.render.terminal_text import (
    RESET_SGR,
    clip_display,
    display_width,
    normalize_line,
    visual_cells,
)


@dataclass(frozen=True)
class SegmentChange:
    """Describe one changed run of terminal cells."""

    row: int
    column: int
    content: str
    clear_width: int = 0


def _changed_spans(previous_line: str, current_line: str) -> list[tuple[int, int]]:
    """Return zero-based half-open spans of unequal visual cells."""
    previous_cells = visual_cells(previous_line)
    current_cells = visual_cells(current_line)
    changed_columns = [
        column
        for column, (previous, current) in enumerate(
            zip_longest(previous_cells, current_cells)
        )
        if previous != current
    ]

    if not changed_columns:
        return []

    spans: list[tuple[int, int]] = []
    start = previous = changed_columns[0]

    for column in changed_columns[1:]:
        if column != previous + 1:
            spans.append((start, previous + 1))
            start = column
        previous = column

    spans.append((start, previous + 1))
    return spans


def get_segment_changes(
    previous_lines: list[str],
    current_lines: list[str],
) -> list[SegmentChange]:
    """Return changed visual segments between complete terminal frames."""
    changes: list[SegmentChange] = []

    for row in range(max(len(previous_lines), len(current_lines))):
        previous_exists = row < len(previous_lines)
        current_exists = row < len(current_lines)
        previous_raw = previous_lines[row] if previous_exists else ""
        current_raw = current_lines[row] if current_exists else ""

        if previous_exists == current_exists and previous_raw == current_raw:
            continue

        previous_line = normalize_line(
            previous_raw
        )
        current_line = normalize_line(
            current_raw
        )

        if previous_line == current_line:
            if previous_exists != current_exists:
                changes.append(
                    SegmentChange(
                        row=row + 1,
                        column=1,
                        content=RESET_SGR + RESET_SGR,
                    )
                )
            continue

        for start, end in _changed_spans(previous_line, current_line):
            clipped = clip_display(current_line, start, end)
            visible_width = display_width(clipped)
            changes.append(
                SegmentChange(
                    row=row + 1,
                    column=start + 1,
                    content=RESET_SGR + clipped + RESET_SGR,
                    clear_width=max(0, end - start - visible_width),
                )
            )

    return changes
```

Each occupied cell stores the full grapheme text, total width, and its offset.
Therefore any grapheme or style difference marks every occupied cell of that
grapheme; the grouped span already begins and ends on safe grapheme boundaries.

- [ ] **Step 8: Verify and commit the segment model**

Run: `uv run pytest -q tests/render/test_terminal_text.py tests/render/test_segment_diff.py`

Expected: all tests pass.

Commit:

```bash
git add src/tuiloom/render/terminal_text.py src/tuiloom/render/segment_diff.py
git add -f tests/render/test_terminal_text.py tests/render/test_segment_diff.py
git commit -m "feat: calculate styled terminal segment changes"
```

### Task 4: Write segment changes through TerminalRenderer

**Files:**
- Modify: `src/tuiloom/render/terminal_renderer.py`
- Modify: `tests/render/test_terminal_renderer.py`
- Delete: `src/tuiloom/render/line_diff.py`
- Delete: `tests/render/test_line_diff.py`

- [ ] **Step 1: Replace line-level expectations with failing segment expectations**

Update imports in `tests/render/test_terminal_renderer.py` as required, then replace `test_changed_input_rewrites_only_the_prompt_line` with:

```python
def test_changed_input_writes_only_the_changed_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)
    renderer.render("1")
    output.seek(0)
    output.truncate()

    renderer.render("12")

    screen = output.getvalue()
    assert "\033[19;17H" in screen
    assert "2" in screen
    assert "Choice?" not in screen
```

Append:

```python
def test_two_changed_regions_produce_two_cursor_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)
    renderer._previous_lines = ["abc DEF ghi JKL"]
    renderer._previous_terminal_size = os.terminal_size((40, 20))

    renderer._write_segment_changes(
        get_segment_changes(
            renderer._previous_lines,
            ["abc XYZ ghi MNO"],
        )
    )

    screen = output.getvalue()
    assert "\033[1;5H" in screen
    assert "\033[1;13H" in screen
    assert "\033[2K" not in screen


def test_cursor_position_uses_visible_ansi_unicode_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_renderer(monkeypatch, StringIO())

    assert renderer._get_cursor_position(
        ["\x1b[31mChoice: 界\x1b[0m"]
    ) == (1, 11)


def test_final_frame_safety_removes_cursor_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_renderer(monkeypatch, StringIO())
    renderer.content_renderer = ContentRenderer("safe\x1b[2Jtext")

    lines = renderer._compose_frame("", 40, 20)

    assert all("\x1b[2J" not in line for line in lines)
```

Import `get_segment_changes` from `segment_diff` for the direct writer test.

- [ ] **Step 2: Run renderer tests and verify RED**

Run: `uv run pytest -q tests/render/test_terminal_renderer.py`

Expected: the renderer still emits complete-line clearing, has no `_write_segment_changes`, and calculates cursor columns with `len()`.

- [ ] **Step 3: Migrate TerminalRenderer to segment changes**

Replace the line-diff import with:

```python
from tuiloom.render.segment_diff import SegmentChange, get_segment_changes
from tuiloom.render.terminal_text import display_width, normalize_line
```

In `render()`, replace `get_line_changes` and `_write_line_changes` with `get_segment_changes` and `_write_segment_changes`.

At the end of `_compose_frame()`, replace the direct split result with:

```python
return [normalize_line(line) for line in render.split("\n")]
```

Replace the line writer with:

```python
def _write_segment_changes(self, changes: list[SegmentChange]) -> None:
    """Write changed terminal-cell segments at precise coordinates."""
    stdout.write("\033[?25l")

    for change in changes:
        stdout.write(f"\033[{change.row};{change.column}H{change.content}")

        if change.clear_width:
            stdout.write(f"\033[{change.clear_width}X")
```

Replace cursor calculation with:

```python
return len(lines), display_width(lines[-1]) + 1
```

- [ ] **Step 4: Remove the obsolete complete-line diff**

Delete `src/tuiloom/render/line_diff.py` and `tests/render/test_line_diff.py` using `apply_patch`. Confirm no imports remain:

Run: `rg -n "LineChange|get_line_changes|line_diff" src tests`

Expected: no matches.

- [ ] **Step 5: Verify renderer behavior and commit**

Run: `uv run pytest -q tests/render/test_segment_diff.py tests/render/test_terminal_renderer.py`

Expected: all segment and terminal renderer tests pass.

Commit:

```bash
git add src/tuiloom/render/terminal_renderer.py src/tuiloom/render/segment_diff.py src/tuiloom/render/line_diff.py
git add -f tests/render/test_terminal_renderer.py tests/render/test_segment_diff.py tests/render/test_line_diff.py
git commit -m "feat: update terminal frames by visual segment"
```

### Task 5: Make every MenuRenderer element ANSI/Unicode-aware

**Files:**
- Modify: `src/tuiloom/render/menu_renderer.py`
- Modify: `tests/render/test_menu_renderer.py`

- [ ] **Step 1: Add failing tests for width, borders, wrapping, commands, and prompts**

Append to `tests/render/test_menu_renderer.py`:

```python
from tuiloom.render.terminal_text import display_width


def visible_lines(render: str) -> list[str]:
    return render.split("\n")


def test_automatic_width_ignores_sgr_and_counts_wide_text() -> None:
    renderer = MenuRenderer(
        make_context(
            app_name="\x1b[31m界界\x1b[0m",
            title="e\u0301",
            width=None,
            commands={"0": (do_nothing, "Q")},
        )
    )

    assert renderer.width == 5


def test_every_box_row_keeps_the_same_visible_width() -> None:
    renderer = MenuRenderer(
        make_context(
            width=20,
            app_name="\x1b[31mApp界\x1b[0m",
            title="\x1b[1mTitle\x1b[0m",
            text="Text 👨‍👩‍👧",
            message="\x1b[38;5;200mMessage\x1b[0m",
            commands={
                "0": (do_nothing, "Quit"),
                "1": (do_nothing, "\x1b[32mGenerate界\x1b[0m"),
            },
        )
    )

    boxed = [line for line in visible_lines(renderer.render()) if line.startswith(("│", "├", "╭", "╰"))]

    assert {display_width(line) for line in boxed} == {22}


def test_two_column_commands_align_with_styled_wide_labels() -> None:
    renderer = MenuRenderer(
        make_context(
            width=30,
            two_columns=True,
            commands={
                "0": (do_nothing, "Quit"),
                "1": (do_nothing, "\x1b[31m界\x1b[0m"),
                "2": (do_nothing, "Emoji 👨‍👩‍👧"),
            },
        )
    )

    assert all(
        display_width(line) == 32
        for line in visible_lines(renderer.render())
        if line.startswith("│")
    )


def test_wrapping_preserves_sgr_and_unicode_boundaries() -> None:
    renderer = MenuRenderer(
        make_context(width=8, text="\x1b[34m界界 界界\x1b[0m")
    )

    wrapped = renderer._wrap_lines(renderer.text or "")

    assert all(display_width(line) <= 6 for line in wrapped)
    assert all("\x1b[34m" in line for line in wrapped)


def test_styled_unicode_prompt_keeps_its_visible_text() -> None:
    renderer = MenuRenderer(
        make_context(width=20, prompt="\x1b[36mChoix界: \x1b[0m")
    )

    prompt = renderer._get_prompt_display()

    assert display_width(prompt) == 9
    assert "\x1b[36m" in prompt
```

- [ ] **Step 2: Run menu tests and verify RED**

Run: `uv run pytest -q tests/render/test_menu_renderer.py`

Expected: width and alignment assertions fail because MenuRenderer uses `len()` and ordinary format alignment.

- [ ] **Step 3: Replace every geometry operation with terminal helpers**

Import:

```python
from tuiloom.render.terminal_text import (
    center_display,
    display_width,
    ljust_display,
    normalize_line,
    normalize_text_lines,
    wrap_display,
)
```

Apply these exact rules throughout `MenuRenderer`:

```python
# _calculate_width
width_requirements = [display_width(self.app_name), display_width(self.title)]

# Multiline text/message/alert requirements
width_requirements.extend(
    display_width(line) + 2 for line in normalize_text_lines(content)
)

# Command requirements
display_width(f" {key}. {command[1]}")

# Centered title rows
f"│{center_display(self.app_name, self.width)}│\n"
f"│{center_display(self.title, self.width)}│\n"

# Every formerly `<{width}` aligned user string
f"│{ljust_display(text, self.width)}│\n"

# Two columns
left_display = ljust_display(left_text, left_width)
right_display = ljust_display(right_text, right_width)
commands_label += f"│{left_display}{right_display}│\n"

# Wrapping
def _wrap_lines(self, text: str) -> list[str]:
    """Wrap safe styled text to the menu's available inner width."""
    wrapped_lines: list[str] = []

    for raw_line in normalize_text_lines(text):
        wrapped_lines.extend(wrap_display(raw_line, self.width - 2))

    return wrapped_lines or [""]
```

Normalize custom prompts before returning them. Default prompts contain no user ANSI and may be returned directly.

Do not alter border construction, menu command semantics, or ScreenContext synchronization.

- [ ] **Step 4: Verify menu rendering and commit**

Run: `uv run pytest -q tests/render/test_menu_renderer.py tests/test_terminal_menu_input.py tests/test_terminal_app.py`

Expected: all menu and lifecycle tests pass.

Commit:

```bash
git add src/tuiloom/render/menu_renderer.py
git add -f tests/render/test_menu_renderer.py
git commit -m "feat: support ANSI Unicode menu geometry"
```

### Task 6: Cover input, full-frame safety, and regressions

**Files:**
- Modify: `tests/render/test_terminal_renderer.py`
- Modify: `README.md`

- [ ] **Step 1: Add integration regressions for styled input and residual clearing**

Append to `tests/render/test_terminal_renderer.py`:

```python
def test_render_restores_cursor_after_styled_wide_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)

    renderer.render("\x1b[31m界\x1b[0m")

    assert output.getvalue().endswith("\033[19;18H\033[?25h")


def test_shorter_segment_erases_only_residual_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)
    renderer._previous_lines = ["abcdef"]
    renderer._previous_terminal_size = os.terminal_size((40, 20))

    changes = get_segment_changes(["abcdef"], ["abc"])
    renderer._write_segment_changes(changes)

    screen = output.getvalue()
    assert "\033[1;4H" in screen
    assert "\033[3X" in screen
    assert "\033[2K" not in screen
```

Recalculate the exact cursor-column expectation from the actual default prompt visible width if the existing menu fixture changes during Task 5; the assertion must remain `display_width(final_line) + 1`.

- [ ] **Step 2: Run integration tests and verify RED or GREEN for the intended reason**

Run: `uv run pytest -q tests/render/test_terminal_renderer.py`

Expected: tests pass because Tasks 4 and 5 already established the unit-level
contracts. If either integration assertion fails, stop and trace the composed
frame before making another production change.

- [ ] **Step 3: Document supported terminal text**

Append to `README.md`:

```markdown
## ANSI styles and Unicode

Every visual Tuiloom string supports SGR colors and styles, including 16-color,
256-color, and true-color sequences. Layout and cursor positioning account for
combining characters, wide CJK text, and emoji grapheme clusters.

Tuiloom intentionally strips terminal control sequences that can move the
cursor, erase the screen, scroll, or change terminal state. The renderer keeps
exclusive control of terminal geometry while preserving user-provided style.
```

- [ ] **Step 4: Run the complete Tuiloom verification**

Run:

```bash
uv run pytest -q
uv run mypy src tests
uv run ruff check src tests
git diff --check
```

Expected:

- every test passes;
- mypy reports no issues;
- Ruff reports no new error;
- `git diff --check` produces no output.

If Ruff reports only pre-existing errors in `src/tuiloom/__init__.py` or `tests/test_public_api.py`, do not silently alter the user's unrelated work. Run Ruff on every file touched by this plan and report the preserved external errors separately.

- [ ] **Step 5: Run the editable Call-Me-Maybe integration**

From `/home/maroard/Bureau/42/Cercle-3/Call-Me-Maybe`, run:

```bash
uv run pytest -q tests/test_terminal_app.py tests/test_main.py
```

Expected: all Call-Me-Maybe terminal integration tests pass against the edited Tuiloom package.

- [ ] **Step 6: Inspect output scope and commit documentation/tests**

Run in both repositories: `git status --short`.

Confirm that Tuiloom contains only the planned files plus the user's preserved modifications and generated caches. Do not stage cache directories or unrelated public-API edits.

Commit:

```bash
git add README.md
git add -f tests/render/test_terminal_renderer.py
git commit -m "docs: describe safe ANSI rendering"
```
