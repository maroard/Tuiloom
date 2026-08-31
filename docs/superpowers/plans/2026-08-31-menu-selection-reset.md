# Menu Selection Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reset each opened menu to its first enabled command and prevent the marker from landing on disabled commands.

**Architecture:** Reuse the existing `_normalize_selection()` invariant, which excludes disabled commands and includes the exit row. Reset `_selected_index` to the top immediately before normalization in `TerminalMenu.run()`, leaving every other menu state intact.

**Tech Stack:** Python 3.12+, Tuiloom, pytest

---

### Task 1: Reset command selection on every menu run

**Files:**
- Modify: `tests/test_menu_modes.py:190-235`
- Modify: `src/tuiloom/terminal_menu.py:499-512`
- Modify: `README.md:163-210`

- [ ] **Step 1: Write failing lifecycle tests**

Add a reusable synchronous loop double and these tests to
`tests/test_menu_modes.py`:

```python
class SelectionLoop:
    def __init__(self, menu: TerminalMenu, observed: list[int]) -> None:
        self.menu = menu
        self.observed = observed

    def run(self) -> None:
        self.observed.append(self.menu._selected_index)
        self.menu._stop_immediately()

    def close(self) -> None:
        pass


def test_menu_run_resets_selection_on_every_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, menu = make_menu()
    menu.add_command("First", lambda context: None)
    second = menu.add_command("Second", lambda context: None)
    app._input_handler = object()  # type: ignore[assignment]
    observed: list[int] = []
    monkeypatch.setattr(
        menu,
        "_create_event_loop",
        lambda: SelectionLoop(menu, observed),
    )

    menu._selected_index = second.position
    menu.run()
    menu._selected_index = second.position
    menu.run()

    assert observed == [0, 0]


@pytest.mark.parametrize(
    ("disabled_positions", "expected"),
    [
        ((0,), 1),
        ((0, 1), 2),
    ],
)
def test_menu_run_skips_disabled_commands_from_the_top(
    monkeypatch: pytest.MonkeyPatch,
    disabled_positions: tuple[int, ...],
    expected: int,
) -> None:
    app, menu = make_menu()
    commands = (
        menu.add_command("First", lambda context: None),
        menu.add_command("Second", lambda context: None),
    )
    for position in disabled_positions:
        menu.disable_command(commands[position])
    app._input_handler = object()  # type: ignore[assignment]
    observed: list[int] = []
    monkeypatch.setattr(
        menu,
        "_create_event_loop",
        lambda: SelectionLoop(menu, observed),
    )

    menu._selected_index = len(menu.commands)
    menu.run()

    assert observed == [expected]
```

The second parametrized case expects index `2`, which is the automatic exit row
when both commands are disabled.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
uv run pytest tests/test_menu_modes.py::test_menu_run_resets_selection_on_every_open tests/test_menu_modes.py::test_menu_run_skips_disabled_commands_from_the_top -v
```

Expected: all cases FAIL because `run()` preserves the existing valid selection.

- [ ] **Step 3: Implement the minimal lifecycle reset**

In `TerminalMenu.run()`, reset before the existing normalization:

```python
self._running = True
self._input_buffer = ""
self._focused_panel = None
self._selected_index = 0
self._normalize_selection()
```

- [ ] **Step 4: Document the reopening rule**

Add this paragraph to the Commands and submenus section of `README.md`:

```markdown
Every time a menu opens, its marker starts on the first enabled command from
the top. Disabled commands are skipped during initialization and navigation; if
all commands are disabled, the marker starts on the automatic `Back` or `Quit`
row.
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_menu_modes.py tests/test_commands_and_menu.py -v
```

Expected: all tests PASS, including existing dynamic disable and navigation
coverage.

- [ ] **Step 6: Run the complete quality gate**

Run:

```bash
make check
git diff --check
```

Expected: Ruff, format, mypy, all tests, and the coverage threshold PASS.

- [ ] **Step 7: Commit and update PR #3**

```bash
git add src/tuiloom/terminal_menu.py tests/test_menu_modes.py README.md
git commit -m "fix: reset selection when opening menus"
git push
```

