# Line Differential Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render only changed terminal lines while displaying the active command input and positioning a visible cursor after it.

**Architecture:** Keep frame composition and terminal output in `TerminalRenderer`, but move frame comparison into a small `LineChange` representation and `get_line_changes()` function. `TerminalMenu` continues to own input state and passes it into the renderer; `TerminalRenderer` caches the successfully written frame and falls back to a full redraw on the first frame or terminal resize.

**Tech Stack:** Python 3.12, ANSI terminal control sequences, pytest, Ruff, mypy

---

## File Structure

- Create `src/tuiloom/render/line_diff.py`: represent complete-line replacements and calculate them independently from terminal output, providing the boundary where segment changes can be introduced later.
- Create `tests/render/test_line_diff.py`: specify changed, added, and removed line detection.
- Modify `src/tuiloom/render/terminal_renderer.py`: compose logical frames, cache successful output, choose full or differential rendering, write ANSI updates, and position the input cursor.
- Create `tests/render/test_terminal_renderer.py`: specify full rendering, unchanged-frame suppression, changed-line output, resize invalidation, and cursor positioning.
- Modify `src/tuiloom/terminal_menu.py`: pass the current command buffer to `TerminalRenderer.render()`.
- Create `tests/test_terminal_menu_input.py`: specify that typing and backspace forward visible input to rendering.

### Task 1: Complete-line diff boundary

**Files:**
- Create: `src/tuiloom/render/line_diff.py`
- Create: `tests/render/test_line_diff.py`

- [ ] **Step 1: Write failing tests for changed, added, and removed lines**

```python
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
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `pytest tests/render/test_line_diff.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'tuiloom.render.line_diff'`.

- [ ] **Step 3: Implement the minimal line diff unit**

```python
from dataclasses import dataclass
from itertools import zip_longest


@dataclass(frozen=True)
class LineChange:
    """Describe one complete terminal line replacement."""

    row: int
    content: str


def get_line_changes(
    previous_lines: list[str],
    current_lines: list[str],
) -> list[LineChange]:
    """Return the complete lines that differ between two terminal frames."""
    changes: list[LineChange] = []

    for row, (previous_line, current_line) in enumerate(
        zip_longest(previous_lines, current_lines, fillvalue=""),
        start=1,
    ):
        if previous_line != current_line:
            changes.append(LineChange(row=row, content=current_line))

    return changes
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `pytest tests/render/test_line_diff.py -v`

Expected: three tests pass.

- [ ] **Step 5: Commit the isolated diff boundary**

```bash
git add src/tuiloom/render/line_diff.py tests/render/test_line_diff.py
git commit -m "feat: calculate terminal line changes"
```

### Task 2: Stateful differential terminal output

**Files:**
- Modify: `src/tuiloom/render/terminal_renderer.py`
- Create: `tests/render/test_terminal_renderer.py`

- [ ] **Step 1: Write a failing test for the initial frame and visible input cursor**

Build a renderer with static content and a minimal `ScreenContext`, replace the
module's `stdout` with `StringIO`, and replace `get_terminal_size` with a lambda
returning `os.terminal_size((40, 12))`:

```python
def test_first_render_draws_full_frame_and_positions_input_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)

    renderer.render("12")

    screen = output.getvalue()
    assert screen.startswith("\033[?25l\033[H\033[J")
    assert "Choice? (0-1): 12" in screen
    assert screen.endswith("\033[12;18H\033[?25h")
```

- [ ] **Step 2: Run the focused test and verify the signature failure**

Run: `pytest tests/render/test_terminal_renderer.py::test_first_render_draws_full_frame_and_positions_input_cursor -v`

Expected: FAIL because `TerminalRenderer.render()` does not accept an input buffer and the generated frame does not contain the input.

- [ ] **Step 3: Implement frame composition and complete redraw state**

Add `_previous_lines: list[str] | None` and `_previous_terminal_size: os.terminal_size | None` to `TerminalRenderer`. Change `render` to accept `input_buffer: str = ""`, append it to `menu_render`, split the full render with `split("\n")`, and use helpers with these responsibilities:

```python
def _compose_frame(
    self,
    input_buffer: str,
    terminal_width: int,
    terminal_height: int,
) -> list[str]:
    rendered_content = self.content_renderer.update()
    menu_render = self.menu_renderer.render() + input_buffer
    menu_lines = menu_render.splitlines() or [""]
    menu_height = len(menu_lines)
    menu_width = max(len(line) for line in menu_lines)
    viewport_height = terminal_height - menu_height - self.spacing

    if terminal_width <= 0 or viewport_height <= 0 or menu_width > terminal_width:
        return ["Terminal window is too small."]

    if self.viewport is None:
        self.viewport = Viewport(rendered_content, terminal_width, viewport_height)
    else:
        self.viewport.content = rendered_content
        self.viewport.width = terminal_width
        self.viewport.height = viewport_height

    viewport_render = self.viewport.render()
    frame = viewport_render + "\n" * self.spacing + menu_render

    return frame.split("\n")

def _write_full_frame(self, lines: list[str]) -> None:
    stdout.write("\033[?25l\033[H\033[J" + "\n".join(lines))

def _get_cursor_position(self, lines: list[str]) -> tuple[int, int]:
    return len(lines), len(lines[-1]) + 1

def _restore_input_cursor(self, lines: list[str]) -> None:
    row, column = self._get_cursor_position(lines)
    stdout.write(f"\033[{row};{column}H\033[?25h")
```

Write the full frame on the first render, restore the cursor, flush, then cache
the lines and terminal size. The terminal-too-small frame is represented as
`["Terminal window is too small."]` by `_compose_frame` so it follows the same
state and cursor rules.

- [ ] **Step 4: Run the initial-frame test and verify it passes**

Run: `pytest tests/render/test_terminal_renderer.py::test_first_render_draws_full_frame_and_positions_input_cursor -v`

Expected: PASS.

- [ ] **Step 5: Write failing tests for unchanged output and a changed input line**

```python
def test_unchanged_frame_produces_no_additional_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)
    renderer.render("1")
    output.seek(0)
    output.truncate()

    renderer.render("1")

    assert output.getvalue() == ""


def test_changed_input_rewrites_only_the_prompt_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)
    renderer.render("1")
    output.seek(0)
    output.truncate()

    renderer.render("12")

    assert output.getvalue() == (
        "\033[?25l"
        "\033[12;1H\033[2KChoice? (0-1): 12"
        "\033[12;18H\033[?25h"
    )
```

- [ ] **Step 6: Run both tests and verify differential behavior is missing**

Run: `pytest tests/render/test_terminal_renderer.py -v`

Expected: the initial-frame test passes; unchanged and changed-input tests fail because every frame is still fully redrawn.

- [ ] **Step 7: Implement differential writes through `LineChange`**

Import `get_line_changes` and add:

```python
def _write_line_changes(self, changes: list[LineChange]) -> None:
    stdout.write("\033[?25l")

    for change in changes:
        stdout.write(f"\033[{change.row};1H\033[2K{change.content}")
```

In `render()`, if the size is unchanged and `_previous_lines` exists, calculate
the changes. Return without writing when the list is empty. Otherwise write
only those changes, restore the input cursor, flush, and update the cache only
after all writes succeed.

- [ ] **Step 8: Run the renderer tests and verify they pass**

Run: `pytest tests/render/test_terminal_renderer.py -v`

Expected: all current renderer tests pass.

- [ ] **Step 9: Write a failing resize test**

Use a mutable terminal-size holder in the monkeypatch, render once at 40 by 12,
clear the captured output, change the holder to 50 by 14, and render again:

```python
assert output.getvalue().startswith("\033[?25l\033[H\033[J")
```

- [ ] **Step 10: Run the resize test and verify it fails**

Run: `pytest tests/render/test_terminal_renderer.py::test_resize_forces_complete_redraw -v`

Expected: FAIL if the renderer tries to apply line changes after a resize.

- [ ] **Step 11: Make terminal-size changes invalidate the cached frame**

Compare the current `os.terminal_size` with `_previous_terminal_size`. Call
`_write_full_frame()` when they differ, even if previous lines exist, then
restore the input cursor and update both caches.

- [ ] **Step 12: Run all renderer and diff tests**

Run: `pytest tests/render/test_terminal_renderer.py tests/render/test_line_diff.py -v`

Expected: all tests pass.

- [ ] **Step 13: Commit stateful terminal rendering**

```bash
git add src/tuiloom/render/terminal_renderer.py tests/render/test_terminal_renderer.py
git commit -m "feat: render terminal changes by line"
```

### Task 3: Connect the menu input buffer

**Files:**
- Modify: `src/tuiloom/terminal_menu.py`
- Create: `tests/test_terminal_menu_input.py`

- [ ] **Step 1: Write a failing menu input forwarding test**

Construct a menu with a lightweight application, attach a recording renderer,
invoke `_handle_char(InputEvent("char", "a"))`, and render through a new small
private method used by the loop:

```python
def test_menu_forwards_typed_input_to_terminal_renderer() -> None:
    menu = make_menu()
    renderer = RecordingTerminalRenderer()
    menu.terminal_renderer = renderer

    menu._handle_char(InputEvent("char", "a"))
    menu._render()

    assert renderer.input_buffers == ["a"]
```

Add the corresponding backspace test by starting with `_input_buffer = "ab"`,
calling `_handle_backspace()`, calling `_render()`, and asserting `['a']`.

- [ ] **Step 2: Run the menu tests and verify the missing helper failure**

Run: `pytest tests/test_terminal_menu_input.py -v`

Expected: FAIL because `TerminalMenu` has no `_render()` method.

- [ ] **Step 3: Add the minimal forwarding boundary**

Replace the direct loop call with `_render()` and implement:

```python
def _render(self) -> None:
    """Render the menu with the current command input."""
    if self.terminal_renderer is not None:
        self.terminal_renderer.render(self._input_buffer)
```

- [ ] **Step 4: Run input and command dispatch tests**

Run: `pytest tests/test_terminal_menu_input.py tests/test_command_dispatch.py -v`

Expected: all tests pass, confirming visible input without changing command
buffer semantics.

- [ ] **Step 5: Commit menu integration**

```bash
git add src/tuiloom/terminal_menu.py tests/test_terminal_menu_input.py
git commit -m "feat: display active command input"
```

### Task 4: Full verification

**Files:**
- Modify only if verification exposes a defect in the files already listed.

- [ ] **Step 1: Run the complete test suite**

Run: `pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Run formatting and lint checks**

Run: `ruff format --check src tests && ruff check src tests`

Expected: both commands exit successfully with no diagnostics.

- [ ] **Step 3: Run strict type checking**

Run: `mypy`

Expected: success with no issues.

- [ ] **Step 4: Inspect the final diff without disturbing user changes**

Run: `git status --short && git diff --check && git diff HEAD~3 -- src/tuiloom/render/line_diff.py src/tuiloom/render/terminal_renderer.py src/tuiloom/terminal_menu.py tests/render/test_line_diff.py tests/render/test_terminal_renderer.py tests/test_terminal_menu_input.py`

Expected: no whitespace errors; the pre-existing `src/tuiloom/__init__.py` edit
and generated `__pycache__` directories remain outside feature commits.
