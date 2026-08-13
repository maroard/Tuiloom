# Stream Auto-Scroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add disabled, smart, and strict vertical auto-scroll policies for iterator-backed `TerminalMenu` content.

**Architecture:** `TerminalMenu` exposes a validated mode property, `EventLoop` applies it only after nonempty iterator batches, `TerminalRenderer` owns temporary smart-follow state, and `Viewport` owns bottom-boundary geometry. A pending follow flag handles batches received before the first viewport composition without coupling source workers to viewport dimensions.

**Tech Stack:** Python 3.12, standard-library typing, pytest, mypy strict, Ruff

---

## File Structure

- Modify `src/tuiloom/terminal_menu.py`: declare `AutoScrollMode`, expose the validated constructor/property API, and preserve smart-mode semantics around manual vertical input.
- Modify `src/tuiloom/__init__.py`: export `AutoScrollMode` alongside the existing public API while preserving the user's uncommitted `InputBehavior` export.
- Modify `src/tuiloom/render/viewport.py`: expose bottom-boundary queries and movement.
- Modify `src/tuiloom/render/terminal_renderer.py`: retain pending follow requests and smart-follow suspension state.
- Modify `src/tuiloom/event_loop/event_loop.py`: apply auto-scroll only after nonempty iterator batches and reset it for every installed source.
- Modify `tests/render/test_viewport.py`: test bottom calculations and horizontal-offset preservation.
- Modify `tests/render/test_terminal_renderer.py`: test disabled, smart, strict, manual, pending, and source-reset behavior.
- Modify `tests/event_loop/test_event_loop.py`: prove only iterator data batches request auto-scroll.
- Modify `tests/test_terminal_menu_input.py`: test constructor/property validation and vertical-input integration.
- Modify `tests/test_public_api.py`: add a focused `AutoScrollMode` export test without changing the exact-symbol expectation owned by the user's pending `InputBehavior` work.
- Modify `README.md`: document the three public modes with a concise iterator example.

The worktree already contains unrelated, uncommitted `InputBehavior` changes in `src/tuiloom/__init__.py`, `src/tuiloom/command.py`, and `src/tuiloom/terminal_menu.py`. Preserve those hunks. Do not commit or rewrite them as part of auto-scroll; use patch staging for overlapping files.

### Task 1: Add viewport bottom geometry

**Files:**
- Modify: `src/tuiloom/render/viewport.py`
- Modify: `tests/render/test_viewport.py`

- [ ] **Step 1: Write failing bottom-boundary tests**

Append:

```python
def test_viewport_reports_and_reaches_bottom_without_horizontal_movement() -> None:
    viewport = Viewport(content(), width=3, height=2)
    viewport.scroll_right()

    assert viewport.is_at_bottom() is False

    viewport.scroll_to_bottom()

    assert viewport.is_at_bottom() is True
    assert (viewport.offset_x, viewport.offset_y) == (1, 1)


def test_short_content_is_already_at_bottom() -> None:
    viewport = Viewport(content(), width=4, height=4)

    assert viewport.is_at_bottom() is True

    viewport.scroll_to_bottom()

    assert viewport.offset_y == 0
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest -q tests/render/test_viewport.py -k bottom`

Expected: failures report missing `is_at_bottom()` and `scroll_to_bottom()`.

- [ ] **Step 3: Implement the geometry methods**

Add one shared boundary helper and the two designed operations:

```python
def _get_max_offset_y(self) -> int:
    """Return the current lower vertical boundary."""
    return max(0, self.content.height - self.height)

def is_at_bottom(self) -> bool:
    """Return whether the vertical offset is at its current lower boundary."""
    return self.offset_y >= self._get_max_offset_y()

def scroll_to_bottom(self) -> None:
    """Move the vertical offset to its current lower boundary."""
    self.offset_y = self._get_max_offset_y()
```

Reuse `_get_max_offset_y()` in `render()` and `scroll_down()` so the boundary is defined once. Do not alter `offset_x`.

- [ ] **Step 4: Run viewport verification and verify GREEN**

Run: `uv run pytest -q tests/render/test_viewport.py && uv run mypy src/tuiloom/render/viewport.py tests/render/test_viewport.py`

Expected: all viewport tests pass and mypy reports no issues.

- [ ] **Step 5: Commit viewport geometry**

```bash
git add src/tuiloom/render/viewport.py tests/render/test_viewport.py
git commit -m "feat: expose viewport bottom geometry"
```

### Task 2: Add renderer auto-scroll policies

**Files:**
- Modify: `src/tuiloom/render/terminal_renderer.py`
- Modify: `tests/render/test_terminal_renderer.py`

- [ ] **Step 1: Write failing smart and strict policy tests**

Create a helper that installs tall streaming content and performs one render so a viewport exists. Add:

```python
def test_smart_auto_scroll_follows_new_stream_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_stream_renderer(monkeypatch)
    renderer.content_renderer.append_stream_batch(["first\nsecond\nthird"])

    renderer.apply_stream_auto_scroll("smart")
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.is_at_bottom() is True


def test_strict_auto_scroll_returns_to_bottom_after_manual_scroll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_stream_renderer(monkeypatch)
    renderer.content_renderer.append_stream_batch(["1\n2\n3\n4"])
    renderer.apply_stream_auto_scroll("strict")
    renderer.render()
    renderer.scroll_up()
    renderer.content_renderer.append_stream_batch(["\n5"])

    renderer.apply_stream_auto_scroll("strict")
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.is_at_bottom() is True
```

Give `make_stream_renderer()` a terminal height that leaves a two-line viewport, so bottom movement is observable.

- [ ] **Step 2: Run policy tests and verify RED**

Run: `uv run pytest -q tests/render/test_terminal_renderer.py -k auto_scroll`

Expected: failures report missing `apply_stream_auto_scroll()`.

- [ ] **Step 3: Implement pending follow and strict behavior**

Add state initialized in `TerminalRenderer.__init__()`:

```python
self._smart_auto_scroll_active = True
self._pending_auto_scroll: AutoScrollMode | None = None
```

Import `AutoScrollMode` under `TYPE_CHECKING` to avoid a runtime cycle. Add:

```python
def apply_stream_auto_scroll(self, mode: AutoScrollMode | None) -> None:
    """Apply or defer one iterator-batch vertical following policy."""
    if mode is None:
        self._pending_auto_scroll = None
        return

    if mode == "smart" and not self._smart_auto_scroll_active:
        return

    if self.viewport is None:
        self._pending_auto_scroll = mode
        return

    self.viewport.scroll_to_bottom()

def reset_stream_auto_scroll(self) -> None:
    """Reset transient following state for a newly installed source."""
    self._smart_auto_scroll_active = True
    self._pending_auto_scroll = None
```

In `_compose_frame()`, after viewport creation or geometry update and before `viewport.render()`, apply `_pending_auto_scroll` through the same method and clear it first. This ensures the current viewport height is available and prevents recursion from retaining the request.

- [ ] **Step 4: Write failing manual smart-mode tests**

Add:

```python
def test_successful_scroll_up_suspends_smart_auto_scroll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_stream_renderer(monkeypatch)
    fill_and_follow_bottom(renderer, "smart")

    renderer.scroll_up()
    preserved_offset = renderer.viewport.offset_y if renderer.viewport else -1
    renderer.content_renderer.append_stream_batch(["\nnew"])
    renderer.apply_stream_auto_scroll("smart")
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.offset_y == preserved_offset


def test_ineffective_scroll_up_does_not_suspend_smart_auto_scroll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_stream_renderer(monkeypatch)
    renderer.scroll_up()
    renderer.content_renderer.append_stream_batch(["1\n2\n3"])

    renderer.apply_stream_auto_scroll("smart")
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.is_at_bottom() is True


def test_manual_return_to_bottom_resumes_smart_auto_scroll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_stream_renderer(monkeypatch)
    fill_and_follow_bottom(renderer, "smart")
    renderer.scroll_up()

    while renderer.viewport is not None and not renderer.viewport.is_at_bottom():
        renderer.scroll_down()

    renderer.content_renderer.append_stream_batch(["\nnew"])
    renderer.apply_stream_auto_scroll("smart")
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.is_at_bottom() is True
```

- [ ] **Step 5: Run manual tests and verify RED**

Run: `uv run pytest -q tests/render/test_terminal_renderer.py -k 'smart_auto_scroll or ineffective_scroll'`

Expected: the successful-upward-scroll test returns to bottom incorrectly or the resume test fails.

- [ ] **Step 6: Implement smart suspension and resumption**

In `scroll_up()`, compare the offset before and after delegating. Suspend smart following only if the viewport actually moved upward:

```python
previous_offset = self.viewport.offset_y
self.viewport.scroll_up()

if self.viewport.offset_y < previous_offset:
    self._smart_auto_scroll_active = False
```

In `scroll_down()`, delegate first, then set `_smart_auto_scroll_active = True` when `viewport.is_at_bottom()` becomes true. Leave horizontal methods unchanged.

Call `reset_stream_auto_scroll()` from `set_content_renderer()` so every source replacement resets suspension.

- [ ] **Step 7: Run complete renderer verification and verify GREEN**

Run: `uv run pytest -q tests/render/test_terminal_renderer.py && uv run mypy src/tuiloom/render/terminal_renderer.py tests/render/test_terminal_renderer.py`

Expected: all terminal-renderer tests pass and mypy reports no issues.

- [ ] **Step 8: Commit renderer behavior**

```bash
git add src/tuiloom/render/terminal_renderer.py tests/render/test_terminal_renderer.py
git commit -m "feat: support smart and strict stream following"
```

### Task 3: Expose and validate the TerminalMenu mode

**Files:**
- Modify: `src/tuiloom/terminal_menu.py`
- Modify: `src/tuiloom/__init__.py`
- Modify: `tests/test_terminal_menu_input.py`
- Modify: `tests/test_public_api.py`

- [ ] **Step 1: Write failing public API and validation tests**

Add a focused export test without editing `test_public_api_contains_only_supported_symbols`, which is temporarily inconsistent with the user's local `InputBehavior` export:

```python
def test_auto_scroll_mode_is_public() -> None:
    assert tuiloom.AutoScrollMode is not None
```

Add menu tests:

```python
def test_menu_auto_scroll_defaults_to_none() -> None:
    assert make_menu().auto_scroll is None


@pytest.mark.parametrize("mode", ["smart", "strict"])
def test_menu_accepts_supported_auto_scroll_modes(mode: str) -> None:
    menu = make_menu()

    menu.auto_scroll = mode  # type: ignore[assignment]

    assert menu.auto_scroll == mode


def test_menu_rejects_invalid_auto_scroll_mode() -> None:
    menu = make_menu()

    with pytest.raises(
        ValueError,
        match="Auto-scroll mode must be 'smart', 'strict', or None",
    ):
        menu.auto_scroll = "bottom"  # type: ignore[assignment]
```

Add one direct-constructor test with `auto_scroll="smart"` and one invalid constructor test.

- [ ] **Step 2: Run public tests and verify RED**

Run: `uv run pytest -q tests/test_public_api.py::test_auto_scroll_mode_is_public tests/test_terminal_menu_input.py -k auto_scroll`

Expected: failures report missing `AutoScrollMode`, constructor parameter, and property. The unrelated exact-symbol test is deliberately excluded.

- [ ] **Step 3: Implement the public type and property**

In `terminal_menu.py`, import `Literal` and declare:

```python
type AutoScrollMode = Literal["smart", "strict"]
```

Add `auto_scroll: AutoScrollMode | None = None` after existing optional constructor arguments. Store `_auto_scroll` and validate through the public property:

```python
@property
def auto_scroll(self) -> AutoScrollMode | None:
    """Return the iterator auto-scroll policy used by this menu."""
    return self._auto_scroll

@auto_scroll.setter
def auto_scroll(self, mode: AutoScrollMode | None) -> None:
    """Validate and replace the iterator auto-scroll policy."""
    if mode not in (None, "smart", "strict"):
        raise ValueError(
            "Auto-scroll mode must be 'smart', 'strict', or None, "
            f"got {mode!r}"
        )

    if mode == self._auto_scroll:
        return

    self._auto_scroll = mode

    if self.terminal_renderer is not None:
        self.terminal_renderer.reset_stream_auto_scroll()
```

Initialize `_auto_scroll` to `None` before assigning `self.auto_scroll = auto_scroll`. This property ensures runtime mutations are validated and mode transitions reset smart suspension without asking `EventLoop` to remember a previous mode.

Export `AutoScrollMode` from `tuiloom.__init__` and add it to `__all__`. Preserve the user's local `InputBehavior` imports and changes in both overlapping files. Do not add `InputBehavior` to the exact-symbol test in this task.

- [ ] **Step 4: Run public tests and verify GREEN**

Run: `uv run pytest -q tests/test_public_api.py::test_auto_scroll_mode_is_public tests/test_terminal_menu_input.py -k auto_scroll`

Expected: all selected tests pass, including the public export, both auto-scroll modes, and invalid values.

- [ ] **Step 5: Commit only auto-scroll hunks**

Use patch staging because both production files contain unrelated local work:

```bash
git add -p src/tuiloom/terminal_menu.py src/tuiloom/__init__.py
git add tests/test_terminal_menu_input.py tests/test_public_api.py
git diff --cached --check
git commit -m "feat: expose stream auto-scroll modes"
```

Before committing, inspect `git diff --cached` and confirm no `InputBehavior`, input-mode, or unrelated command changes are staged.

### Task 4: Connect iterator batches to auto-scroll

**Files:**
- Modify: `src/tuiloom/event_loop/event_loop.py`
- Modify: `tests/event_loop/test_event_loop.py`

- [ ] **Step 1: Write failing event-loop delegation tests**

Extend `RecordingTerminalRenderer` with `auto_scroll_modes` and `reset_auto_scroll_calls`. Add:

```python
def test_iterator_batch_applies_current_menu_auto_scroll_mode() -> None:
    loop, _, _, terminal_renderer = make_loop(source=iter(()))
    loop.menu.auto_scroll = "strict"
    loop.source_events.put(SourceEvent(loop.generation, "data", "chunk"))

    loop._drain_source_events()

    assert terminal_renderer.auto_scroll_modes == ["strict"]
    loop.close()


def test_empty_iterator_event_drain_does_not_apply_auto_scroll() -> None:
    loop, _, _, terminal_renderer = make_loop(source=iter(()))
    loop.menu.auto_scroll = "strict"

    loop._drain_source_events()

    assert terminal_renderer.auto_scroll_modes == []
    loop.close()


def test_dynamic_result_does_not_apply_auto_scroll() -> None:
    loop, _, _, terminal_renderer = make_loop(source=lambda: "dynamic")
    loop.menu.auto_scroll = "strict"
    loop.source_events.put(SourceEvent(loop.generation, "data", "dynamic"))

    loop._drain_source_events()

    assert terminal_renderer.auto_scroll_modes == []
    loop.close()
```

Also assert that `install_source()` calls `reset_stream_auto_scroll()` once for a replacement iterator.

- [ ] **Step 2: Run delegation tests and verify RED**

Run: `uv run pytest -q tests/event_loop/test_event_loop.py -k auto_scroll`

Expected: iterator delegation and reset assertions fail because the methods are not called.

- [ ] **Step 3: Apply the policy after nonempty iterator batches**

In `_drain_source_events()`, immediately after `append_stream_batch(chunks)` and before `request_render()`, add:

```python
self.terminal_renderer.apply_stream_auto_scroll(self.menu.auto_scroll)
```

Do not add this call to the dynamic branch or completion-only events.

In `install_source()`, rely on `TerminalRenderer.set_content_renderer()` to reset the follow state. The recording fake should implement that reset as part of `set_content_renderer()` exactly like the production renderer; avoid a duplicate reset call in `EventLoop`.

- [ ] **Step 4: Run event-loop verification and verify GREEN**

Run: `uv run pytest -q tests/event_loop/test_event_loop.py && uv run mypy src/tuiloom/event_loop/event_loop.py tests/event_loop/test_event_loop.py`

Expected: all event-loop tests pass and mypy reports no issues.

- [ ] **Step 5: Commit iterator delegation**

```bash
git add src/tuiloom/event_loop/event_loop.py tests/event_loop/test_event_loop.py
git commit -m "feat: follow streamed iterator batches"
```

### Task 5: Verify integration, resize compatibility, and documentation

**Files:**
- Modify: `README.md`
- Verify: `tests/event_loop/test_event_loop.py`
- Verify: `tests/render/test_terminal_renderer.py`
- Verify: `tests/render/test_viewport.py`

- [ ] **Step 1: Add the user-facing example**

Append to `README.md` under streaming performance:

```markdown
Iterator content can follow its newest output automatically:

```python
menu.auto_scroll = "smart"   # pauses after manual upward scrolling
menu.auto_scroll = "strict"  # returns to the bottom after every batch
menu.auto_scroll = None       # disabled, the default
```

Auto-scroll is vertical and applies only to iterator-backed content.
```

- [ ] **Step 2: Run focused behavioral verification**

Run: `uv run pytest -q tests/render/test_viewport.py tests/render/test_terminal_renderer.py tests/event_loop/test_event_loop.py tests/test_terminal_menu_input.py tests/test_public_api.py`

Expected: all focused tests pass, including terminal resize and terminal-too-small regressions.

- [ ] **Step 3: Run formatting, lint, and strict typing**

Run: `uv run ruff format --check src tests benchmarks && uv run ruff check src tests benchmarks && uv run mypy`

Expected: all commands exit successfully with no diagnostics. If the unrelated local `InputBehavior` work is temporarily inconsistent, report its exact diagnostics separately and run the equivalent checks on auto-scroll files; do not modify unrelated behavior to make this feature green.

- [ ] **Step 4: Run the complete test suite**

Run: `uv run pytest -q`

Expected: every committed test and auto-scroll regression passes. If the pre-existing local `InputBehavior` public-API expectation still fails independently, report that single known failure separately with the passing auto-scroll test count.

- [ ] **Step 5: Verify Call-Me-Maybe compatibility**

From `/home/maroard/Bureau/42/Cercle-3/Call-Me-Maybe`, run:

```bash
PYTHONPATH=/home/maroard/Bureau/42/Tuiloom/src .venv/bin/pytest -q
```

Expected: all Call-Me-Maybe tests pass without consumer source changes. An optional interactive run may enable `menu.auto_scroll = "smart"`, but changing Call-Me-Maybe is outside this task.

- [ ] **Step 6: Commit documentation and inspect repository state**

```bash
git add README.md
git commit -m "docs: describe stream auto-scroll modes"
git status --short
git diff --check
```

Expected: only the user's pre-existing `InputBehavior` changes remain uncommitted; no auto-scroll work remains unstaged.
