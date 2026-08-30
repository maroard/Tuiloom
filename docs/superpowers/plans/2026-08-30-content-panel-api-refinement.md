# Content Panel API Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename panel creation to `add_content_panel()` and move every panel mutation from `TerminalMenu` onto the returned `ContentPanel` handle.

**Architecture:** `TerminalMenu` remains the owner of panel ordering, renderer invalidation, and worker lifecycle, but exposes only panel creation and its ordered `content_panels` view. `ContentPanel` exposes explicit mutation methods that delegate to private owner methods, preserving centralized validation and stable handle identity without duplicating public APIs.

**Tech Stack:** Python 3.12+, pytest, mypy strict mode, Ruff.

---

## File map

- Modify `src/tuiloom/content_panel.py`: add the five explicit public mutation methods.
- Modify `src/tuiloom/terminal_menu.py`: rename panel creation, make owner-side mutations private, and migrate legacy/internal calls.
- Modify `src/tuiloom/event_loop/event_loop.py`: use the approved panel API for dynamically managed panels.
- Modify `tests/test_content_panels.py`: specify creation, explicit mutations, removal, and invalid-handle behavior.
- Modify `tests/test_public_api.py`: assert the approved public names and absence of discarded aliases.
- Modify affected tests under `tests/`: migrate all call sites to the approved API.
- Modify `tests/test_pty.py`: exercise `add_content_panel()` in a real terminal.
- Do not modify `README.md`: documentation remains blocked until the post-implementation signature review.

### Task 1: Specify the approved public surface

**Files:**
- Modify: `tests/test_content_panels.py`
- Modify: `tests/test_public_api.py`

- [ ] **Step 1: Rewrite the stable-handle test around explicit panel methods**

Replace menu-owned mutations in `test_content_panels_are_stable_ordered_handles` with:

```python
metrics = menu.add_content_panel(
    lambda: "42",
    description="Metrics",
    auto_scroll="smart",
    position=0,
)

metrics.set_description("Live metrics")
metrics.set_auto_scroll("strict")
metrics.move(1)

assert metrics.description == "Live metrics"
assert metrics.auto_scroll == "strict"
assert metrics.position == 1
```

- [ ] **Step 2: Specify source replacement and removal on the handle**

Add or update focused tests with these operations:

```python
def test_panel_explicit_methods_mutate_through_the_stable_handle() -> None:
    menu = make_menu()
    panel = menu.add_content_panel("old", description="Old")

    panel.set_source("new")
    panel.set_description("New")
    panel.set_auto_scroll("strict")
    panel.move(0)

    assert panel is menu.content_panels[0]
    assert panel.description == "New"
    assert panel.auto_scroll == "strict"

    panel.remove()
    assert panel not in menu.content_panels


def test_removed_panel_rejects_every_explicit_mutation() -> None:
    panel = make_menu().content_panels[0]
    panel.remove()

    operations = (
        lambda: panel.set_source("new"),
        lambda: panel.set_description("New"),
        lambda: panel.set_auto_scroll("smart"),
        lambda: panel.move(0),
        panel.remove,
    )
    for operation in operations:
        with pytest.raises(ValueError, match="belong"):
            operation()
```

- [ ] **Step 3: Assert the exact public API and discarded aliases**

Update `tests/test_public_api.py` so the documented `TerminalMenu` surface contains `add_content_panel` and not the discarded names, and so `ContentPanel` exposes its methods:

```python
assert hasattr(TerminalMenu, "add_content_panel")
for removed_name in (
    "add_content_source",
    "set_content_panel_source",
    "set_content_panel_description",
    "set_content_panel_auto_scroll",
    "move_content_panel",
    "remove_content_panel",
):
    assert not hasattr(TerminalMenu, removed_name)

for method_name in (
    "set_source",
    "set_description",
    "set_auto_scroll",
    "move",
    "remove",
):
    assert callable(getattr(ContentPanel, method_name))
```

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```bash
uv run pytest tests/test_content_panels.py tests/test_public_api.py -q
```

Expected: failures report missing `add_content_panel()` and `ContentPanel` mutation methods, while the discarded `TerminalMenu` methods still exist.

### Task 2: Implement handle-owned mutations

**Files:**
- Modify: `src/tuiloom/content_panel.py`
- Modify: `src/tuiloom/terminal_menu.py`

- [ ] **Step 1: Add explicit methods to `ContentPanel`**

Add these methods after the read-only properties:

```python
def set_source(self, content_source: ContentSource) -> None:
    """Replace this panel's source without changing its identity."""
    self._menu._set_content_panel_source(self, content_source)

def set_description(self, description: str) -> None:
    """Replace this panel's visible and shutdown description."""
    self._menu._set_content_panel_description(self, description)

def set_auto_scroll(self, mode: AutoScrollMode | None) -> None:
    """Set this panel's iterator auto-scroll policy."""
    self._menu._set_content_panel_auto_scroll(self, mode)

def move(self, position: int) -> None:
    """Move this panel to a zero-based position in its owning menu."""
    self._menu._move_content_panel(self, position)

def remove(self) -> None:
    """Remove this panel and cooperatively retire its worker."""
    self._menu._remove_content_panel(self)
```

- [ ] **Step 2: Rename creation and privatize owner operations**

In `TerminalMenu`, rename the methods without retaining public aliases:

```python
def add_content_panel(
    self,
    content_source: ContentSource,
    *,
    description: str = "Content in progress",
    auto_scroll: AutoScrollMode | None = None,
    position: int | None = None,
) -> ContentPanel:
    """Add an independently rendered content panel and return its handle."""
```

Rename the mutation implementations to private owner methods while preserving their existing bodies and validation:

```python
_set_content_panel_source
_set_content_panel_description
_set_content_panel_auto_scroll
_move_content_panel
_remove_content_panel
```

- [ ] **Step 3: Route legacy primary-panel behavior through the handle**

Update `TerminalMenu.set_content_source()` and the primary `auto_scroll` setter to call the approved handle methods where a primary panel exists:

```python
panel.set_description(description)
panel.set_source(content_source)
```

When no primary panel exists, recreate it with `add_content_panel()` and retain the existing primary-panel assignment and ordering semantics.

- [ ] **Step 4: Run the focused API tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_content_panels.py tests/test_public_api.py -q
```

Expected: all focused API tests pass.

- [ ] **Step 5: Commit the public API refinement**

```bash
git add src/tuiloom/content_panel.py src/tuiloom/terminal_menu.py tests/test_content_panels.py tests/test_public_api.py
git commit -m "refactor: move content mutations onto panel handles"
```

### Task 3: Migrate runtime and integration call sites

**Files:**
- Modify: `src/tuiloom/event_loop/event_loop.py`
- Modify: `src/tuiloom/terminal_menu.py`
- Modify: `tests/event_loop/test_event_loop.py`
- Modify: `tests/render/test_terminal_renderer.py`
- Modify: `tests/test_menu_modes.py`
- Modify: `tests/test_task_exit.py`
- Modify: `tests/test_pty.py`

- [ ] **Step 1: Find every discarded API use**

Run:

```bash
rg -n "add_content_source|set_content_panel_|move_content_panel|remove_content_panel" src tests
```

Expected: matches identify every production and test call site that must migrate; private owner method definitions beginning with `_` may remain.

- [ ] **Step 2: Migrate production call sites**

Use `menu.add_content_panel(...)` when creating panels and handle methods for existing panels:

```python
panel.set_source(source)
panel.set_description(description)
panel.remove()
```

Keep private owner calls confined to `ContentPanel` delegation methods. Do not add compatibility aliases.

- [ ] **Step 3: Migrate unit and PTY tests**

Apply the same public usage consistently:

```python
second = menu.add_content_panel("second", description="Second")
second.set_description("Renamed")
second.set_source(replacement)
second.remove()
```

- [ ] **Step 4: Prove the discarded names are absent from consumers**

Run:

```bash
rg -n "\.add_content_source|\.set_content_panel_|\.move_content_panel|\.remove_content_panel" src tests
```

Expected: no matches. Definitions of private methods such as `_remove_content_panel` are permitted and do not match the leading-dot public-call patterns above.

- [ ] **Step 5: Run all behavior tests**

Run:

```bash
uv run pytest -q
```

Expected: all 188 tests, plus any newly added API test, pass.

- [ ] **Step 6: Commit migrated integrations**

```bash
git add src tests
git commit -m "refactor: adopt explicit content panel API"
```

### Task 4: Verify and present the final API

**Files:**
- Read: `src/tuiloom/content_panel.py`
- Read: `src/tuiloom/terminal_menu.py`
- Do not modify: `README.md`

- [ ] **Step 1: Run all non-documentation quality gates**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src tests
uv run pytest --cov=tuiloom --cov-report=term-missing
```

Expected: Ruff and mypy exit zero, all tests pass, and total coverage remains at or above 90%.

- [ ] **Step 2: Extract exact implemented signatures**

```bash
uv run python - <<'PY'
from inspect import signature
from tuiloom import ContentPanel, TerminalMenu

print(f"TerminalMenu.add_content_panel{signature(TerminalMenu.add_content_panel)}")
for name in (
    "set_source",
    "set_description",
    "set_auto_scroll",
    "move",
    "remove",
):
    print(f"ContentPanel.{name}{signature(getattr(ContentPanel, name))}")
for name in ("description", "position", "auto_scroll"):
    print(f"ContentPanel.{name}: property")
PY
```

- [ ] **Step 3: Stop for user approval before README work**

Present the exact signature output, this usage example, the absence of discarded aliases, and the verified legacy `set_content_source()`/`menu.auto_scroll` behavior. Do not modify `README.md` until the user explicitly approves the implemented API.
