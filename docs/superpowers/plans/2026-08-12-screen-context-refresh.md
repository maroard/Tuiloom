# Screen Context Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh every menu display field from the current `ScreenContext` before each terminal frame.

**Architecture:** `MenuRenderer` owns one explicit synchronization method that copies the context fields and resolves the current width. `TerminalMenu` calls that method immediately before delegating to `TerminalRenderer`, whose existing line diff writes only the changed rows.

**Tech Stack:** Python 3.12, pytest, mypy, flake8

---

## File Structure

- Create `tests/render/test_menu_renderer.py` for renderer synchronization and width behavior.
- Modify `src/tuiloom/render/menu_renderer.py` to centralize initialization and refresh in `update_screen_context()`.
- Modify `tests/test_terminal_menu_input.py` to specify the synchronization boundary in the menu loop.
- Modify `src/tuiloom/terminal_menu.py` to refresh the menu renderer before each frame.

### Task 1: Synchronize the complete menu rendering state

**Files:**
- Create: `tests/render/test_menu_renderer.py`
- Modify: `src/tuiloom/render/menu_renderer.py:8-22`

- [ ] **Step 1: Write tests for replacing every renderer field and resolving width**

```python
from tuiloom.command import CommandContext
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.screen_context.screen_context import ScreenContext


def do_nothing(context: CommandContext) -> None:
    """Provide a command behavior for menu renderer tests."""


def make_context(**changes: object) -> ScreenContext:
    """Build a context with defaults that tests can selectively replace."""
    values = {
        "app_name": "App",
        "menu_name": "Menu",
        "title": "Title",
        "commands": {"0": (do_nothing, "Back")},
    }
    values.update(changes)
    return ScreenContext(**values)  # type: ignore[arg-type]


def test_update_screen_context_replaces_every_rendered_field() -> None:
    renderer = MenuRenderer(make_context(width=20))
    commands = {
        "0": (do_nothing, "Quit"),
        "1": (do_nothing, "Generate"),
    }
    context = make_context(
        app_name="New App",
        title="New Title",
        width=42,
        commands=commands,
        text="Description",
        two_columns=True,
        message="Credits",
        alert="Warning",
        prompt="Continue: ",
    )

    renderer.update_screen_context(context)

    assert renderer.app_name == "New App"
    assert renderer.title == "New Title"
    assert renderer.width == 42
    assert renderer.commands is commands
    assert renderer.text == "Description"
    assert renderer.two_columns is True
    assert renderer.message == "Credits"
    assert renderer.alert == "Warning"
    assert renderer.prompt == "Continue: "
    assert "Credits" in renderer._get_message_display()


def test_update_screen_context_recalculates_automatic_width() -> None:
    renderer = MenuRenderer(make_context(width=None))
    context = make_context(width=None, message="A much longer message")

    renderer.update_screen_context(context)

    assert renderer.width == len("A much longer message") + 2
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest -q tests/render/test_menu_renderer.py`

Expected: FAIL because `MenuRenderer` has no `update_screen_context` method.

- [ ] **Step 3: Add the minimal synchronization method and reuse it from the constructor**

```python
class MenuRenderer:
    """Build a complete terminal menu box from screen context."""

    def __init__(self, screen_context: ScreenContext) -> None:
        """Capture the screen state required to render the menu."""
        self.update_screen_context(screen_context)

    def update_screen_context(self, screen_context: ScreenContext) -> None:
        """Replace the menu state with the current screen context."""
        self.app_name = screen_context.app_name
        self.title = screen_context.title
        self.commands = screen_context.commands
        self.text = screen_context.text
        self.two_columns = screen_context.two_columns
        self.message = screen_context.message
        self.alert = screen_context.alert
        self.prompt = screen_context.prompt

        requested_width = screen_context.width
        self.width = (
            requested_width
            if requested_width is not None
            else self._calculate_width()
        )
```

- [ ] **Step 4: Run the renderer tests and verify GREEN**

Run: `uv run pytest -q tests/render/test_menu_renderer.py tests/render/test_terminal_renderer.py`

Expected: all tests PASS.

- [ ] **Step 5: Commit the renderer synchronization**

```bash
git add src/tuiloom/render/menu_renderer.py tests/render/test_menu_renderer.py
git commit -m "fix: refresh menu renderer screen context"
```

### Task 2: Refresh the renderer at the menu loop boundary

**Files:**
- Modify: `tests/test_terminal_menu_input.py`
- Modify: `src/tuiloom/terminal_menu.py:220-223`

- [ ] **Step 1: Add a test proving synchronization occurs before frame rendering**

Add these recording doubles near `RecordingTerminalRenderer`:

```python
class RecordingMenuRenderer:
    """Record context refreshes without formatting a menu."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.contexts = []

    def update_screen_context(self, screen_context: object) -> None:
        self.contexts.append(screen_context)
        self.events.append("refresh")


class OrderedTerminalRenderer(RecordingTerminalRenderer):
    """Record terminal rendering in a shared event sequence."""

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def render(self, input_buffer: str = "") -> None:
        self.events.append("render")
        super().render(input_buffer)
```

Add the focused behavior test:

```python
def test_menu_refreshes_screen_context_before_rendering() -> None:
    menu = make_menu()
    events: list[str] = []
    menu_renderer = RecordingMenuRenderer(events)
    terminal_renderer = OrderedTerminalRenderer(events)
    menu.menu_renderer = menu_renderer  # type: ignore[assignment]
    menu.terminal_renderer = terminal_renderer
    menu.screen_context.message = "Credits"

    menu._render()

    assert menu_renderer.contexts == [menu.screen_context]
    assert events == ["refresh", "render"]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest -q tests/test_terminal_menu_input.py::test_menu_refreshes_screen_context_before_rendering`

Expected: FAIL because the recorded events contain only `"render"`.

- [ ] **Step 3: Synchronize the active menu renderer before rendering**

Replace `TerminalMenu._render()` with:

```python
def _render(self) -> None:
    """Refresh the menu state and render the current command input."""
    if self.menu_renderer is not None:
        self.menu_renderer.update_screen_context(self.screen_context)

    if self.terminal_renderer is not None:
        self.terminal_renderer.render(self._input_buffer)
```

- [ ] **Step 4: Run focused and full Tuiloom verification**

Run: `uv run pytest -q tests/test_terminal_menu_input.py tests/render`

Expected: all focused rendering tests PASS.

Run: `uv run pytest -q`

Expected: the complete Tuiloom test suite PASS.

Run: `uv run mypy src tests && uv run flake8 src tests && git diff --check`

Expected: all static and formatting checks PASS with no output from `git diff --check`.

- [ ] **Step 5: Commit the loop integration**

```bash
git add src/tuiloom/terminal_menu.py tests/test_terminal_menu_input.py
git commit -m "fix: refresh menu state before each frame"
```

### Task 3: Verify the Call-Me-Maybe integration

**Files:**
- No source changes expected.

- [ ] **Step 1: Run the Call-Me-Maybe tests against the editable Tuiloom dependency**

Run from `/home/maroard/Bureau/42/Cercle-3/Call-Me-Maybe`:

`uv run pytest -q tests/test_terminal_app.py tests/test_main.py`

Expected: all tests PASS and the `Credit` command remains connected to the
Tuiloom screen context.

- [ ] **Step 2: Inspect both worktrees without altering unrelated changes**

Run in each repository: `git status --short`

Expected: only the intended Tuiloom changes and the users' pre-existing
modifications are present; no unrelated file is staged or committed.
