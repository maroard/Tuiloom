# Multi-content Panels and Exit Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add dynamically managed, vertically stacked content panels and replace numeric task-exit prompts with a reactive, keyboard-navigable menu.

**Architecture:** `ContentPanel` is the public stable handle and also owns the private runtime state needed by its renderer, worker, viewport, and auto-scroll. `TerminalMenu` owns the ordered live handles, `EventLoop` routes panel-tagged worker events, and `TerminalRenderer` composes one viewport per visible panel. A small internal task-exit state object projects temporary menu title/rows without mutating `ScreenContext`.

**Tech Stack:** Python 3.12+, pytest, mypy strict mode, Ruff, Blessed terminal I/O, wcwidth-aware rendering.

---

## File map

- Create `src/tuiloom/content_panel.py`: public stable panel handle plus private per-panel runtime fields.
- Create `src/tuiloom/task_exit.py`: internal exit-view mode, selection, labels, and saved navigation state.
- Modify `src/tuiloom/__init__.py`: export `ContentPanel`.
- Modify `src/tuiloom/terminal_menu.py`: ordered panel API, focus cycle, output panels, and exit-view behavior.
- Modify `src/tuiloom/terminal_app.py`: associate captured tasks with their temporary panel and remove obsolete exit-on-completion coupling.
- Modify `src/tuiloom/event_loop/source_event.py`: tag events with their panel and generation.
- Modify `src/tuiloom/event_loop/source_worker.py`: publish panel-tagged events.
- Modify `src/tuiloom/event_loop/event_loop.py`: manage multiple active, pending, and retiring panel workers.
- Modify `src/tuiloom/render/menu_renderer.py`: render temporary task-exit titles and rows without changing `ScreenContext`.
- Modify `src/tuiloom/render/terminal_renderer.py`: compose equal-height vertical panel viewports and route scroll state per panel.
- Modify `tests/test_public_api.py`: assert the new intentional export and documentation.
- Create `tests/test_content_panels.py`: public panel API, ownership, ordering, and active mutation tests.
- Modify `tests/event_loop/test_event_loop.py`: parallel source routing, isolated generations, and cleanup.
- Modify `tests/render/test_terminal_renderer.py`: multi-panel geometry, titles, focus, and independent scrolling.
- Modify `tests/test_menu_modes.py`: focus cycling and legacy single-source compatibility.
- Modify `tests/test_task_exit.py`: arrow-driven exit menu and reactive operation tracking.
- Modify `tests/test_pty.py`: real terminal frame coverage for stacked panels.
- Modify `README.md`: only after the explicit API review checkpoint.

### Task 1: Add the stable `ContentPanel` API

**Files:**
- Create: `src/tuiloom/content_panel.py`
- Modify: `src/tuiloom/terminal_menu.py` (`__init__`, content properties, content mutation methods)
- Modify: `src/tuiloom/__init__.py`
- Create: `tests/test_content_panels.py`
- Modify: `tests/test_public_api.py`

- [ ] **Step 1: Write failing public-handle tests**

Create `tests/test_content_panels.py` with focused tests for construction, order,
mutation, removal, and ownership:

```python
import pytest

from tuiloom import ContentPanel, ScreenContext, TerminalApp, TerminalMenu


def make_menu(content: str | None = "primary") -> TerminalMenu:
    app = TerminalApp("App")
    return TerminalMenu(app, ScreenContext("main", "Main"), content_source=content)


def test_content_panels_are_stable_ordered_handles() -> None:
    menu = make_menu()
    primary = menu.content_panels[0]
    metrics = menu.add_content_source(
        lambda: "42",
        description="Metrics",
        auto_scroll="smart",
        position=0,
    )

    assert isinstance(primary, ContentPanel)
    assert menu.content_panels == (metrics, primary)
    assert metrics.description == "Metrics"
    assert metrics.position == 0
    assert metrics.auto_scroll == "smart"

    menu.set_content_panel_description(metrics, "Live metrics")
    menu.set_content_panel_auto_scroll(metrics, "strict")
    menu.move_content_panel(metrics, 1)

    assert metrics.description == "Live metrics"
    assert metrics.auto_scroll == "strict"
    assert metrics.position == 1


def test_removed_and_foreign_panels_are_rejected() -> None:
    menu = make_menu()
    foreign = make_menu().content_panels[0]
    panel = menu.add_content_source("extra", description="Extra")
    menu.remove_content_panel(panel)

    for invalid in (panel, foreign):
        with pytest.raises(ValueError, match="belong"):
            menu.set_content_panel_description(invalid, "Invalid")
        with pytest.raises(ValueError, match="belong"):
            menu.remove_content_panel(invalid)


def test_legacy_content_api_controls_the_primary_panel() -> None:
    menu = make_menu()
    primary = menu.content_panels[0]
    extra = menu.add_content_source("extra", description="Extra")

    menu.auto_scroll = "strict"
    menu.set_content_source("replacement", description="Replacement")

    assert menu.content_panels == (primary, extra)
    assert primary.description == "Replacement"
    assert primary.auto_scroll == "strict"

    menu.remove_content_panel(primary)
    menu.set_content_source("reborn", description="Primary")
    assert menu.content_panels[0].description == "Primary"
    assert menu.auto_scroll == "strict"
```

Add `ContentPanel` to the expected `tuiloom.__all__` set and documentation class
tuple in `tests/test_public_api.py`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
uv run pytest tests/test_content_panels.py tests/test_public_api.py -q
```

Expected: collection fails because `ContentPanel` and the new menu methods do
not exist.

- [ ] **Step 3: Implement the handle and inactive-menu mutations**

Create `src/tuiloom/content_panel.py` with this public surface and private state:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from tuiloom.render.content_renderer import ContentRenderer, ContentSource
from tuiloom.render.terminal_renderer import AutoScrollMode

if TYPE_CHECKING:
    from tuiloom.event_loop.source_worker import SourceWorker
    from tuiloom.render.viewport import Viewport
    from tuiloom.terminal_menu import TerminalMenu


class ContentPanel:
    """Stable handle for one independently rendered menu content source."""

    __slots__ = (
        "_menu",
        "_source",
        "_description",
        "_auto_scroll",
        "_renderer",
        "_viewport",
        "_worker",
        "_generation",
        "_pending_source",
        "_dynamic_in_flight",
        "_next_dynamic_at",
        "_removed",
        "_retiring",
        "_smart_auto_scroll_active",
        "_pending_auto_scroll",
        "_remove_when_finished",
    )

    def __init__(
        self,
        menu: TerminalMenu,
        source: ContentSource,
        description: str,
        auto_scroll: AutoScrollMode | None,
    ) -> None:
        self._menu = menu
        self._source = source
        self._description = description
        self._auto_scroll = auto_scroll
        self._renderer = ContentRenderer(source)
        self._viewport: Viewport | None = None
        self._worker: SourceWorker | None = None
        self._generation = 0
        self._pending_source: ContentSource | None = None
        self._dynamic_in_flight = False
        self._next_dynamic_at = 0.0
        self._removed = False
        self._retiring = False
        self._smart_auto_scroll_active = True
        self._pending_auto_scroll: AutoScrollMode | None = None
        self._remove_when_finished = False

    @property
    def description(self) -> str:
        """Return the label displayed on this panel."""
        return self._description

    @property
    def position(self) -> int:
        """Return this panel's zero-based position in its owning menu."""
        return self._menu._position_of_content_panel(self)

    @property
    def auto_scroll(self) -> AutoScrollMode | None:
        """Return this panel's iterator auto-scroll policy."""
        return self._auto_scroll
```

In `TerminalMenu`, replace the singular configuration fields with
`_content_panels`, `_primary_content_panel`, and `_default_auto_scroll`. Add the
public methods exercised above. Use the established command-handle pattern:

```python
@property
def content_panels(self) -> tuple[ContentPanel, ...]:
    """Return an immutable ordered view of this menu's content panels."""
    return tuple(self._content_panels)

def add_content_source(
    self,
    content_source: ContentSource,
    *,
    description: str = "Content in progress",
    auto_scroll: AutoScrollMode | None = None,
    position: int | None = None,
) -> ContentPanel:
    """Add an independently rendered content source and return its handle."""
    self._validate_auto_scroll(auto_scroll)
    insert_at = self._validate_content_position(position, allow_end=True)
    panel = ContentPanel(self, content_source, description, auto_scroll)
    self._content_panels.insert(insert_at, panel)
    if self._running and self._event_loop is not None:
        self._event_loop.add_content_panel(panel)
    self._normalize_focus()
    self._invalidate_renderer()
    return panel

def _require_content_panel(self, panel: ContentPanel) -> None:
    if (
        not isinstance(panel, ContentPanel)
        or panel._menu is not self
        or panel._removed
    ):
        raise ValueError("Content panel does not belong to this menu")
```

Add the rest of the menu API with these exact ownership and ordering rules:

```python
def set_content_panel_source(
    self, panel: ContentPanel, content_source: ContentSource
) -> None:
    """Replace one owned panel's source without changing its identity."""
    self._require_content_panel(panel)
    if self._running and self._event_loop is not None:
        self._event_loop.replace_content_panel(panel, content_source)
    else:
        panel._source = content_source
        panel._renderer = ContentRenderer(content_source)
        panel._viewport = None

def set_content_panel_description(
    self, panel: ContentPanel, description: str
) -> None:
    """Replace the visible and shutdown description of one panel."""
    self._require_content_panel(panel)
    panel._description = description
    if panel._worker is not None:
        panel._worker.description = description
    self._invalidate_renderer()

def set_content_panel_auto_scroll(
    self, panel: ContentPanel, mode: AutoScrollMode | None
) -> None:
    """Set one panel's iterator auto-scroll policy."""
    self._require_content_panel(panel)
    self._validate_auto_scroll(mode)
    panel._auto_scroll = mode
    panel._smart_auto_scroll_active = True
    panel._pending_auto_scroll = None

def move_content_panel(self, panel: ContentPanel, position: int) -> None:
    """Move one owned panel to a zero-based position."""
    self._require_content_panel(panel)
    target = self._validate_content_position(position, allow_end=False)
    self._content_panels.remove(panel)
    self._content_panels.insert(target, panel)
    self._invalidate_renderer()

def remove_content_panel(self, panel: ContentPanel) -> None:
    """Remove one owned panel and cooperatively retire its worker."""
    self._require_content_panel(panel)
    self._content_panels.remove(panel)
    if panel is self._primary_content_panel:
        self._primary_content_panel = None
    panel._removed = True
    if self._running and self._event_loop is not None:
        self._event_loop.retire_content_panel(panel)
    self._normalize_focus()
    self._invalidate_renderer()

def _position_of_content_panel(self, panel: ContentPanel) -> int:
    self._require_content_panel(panel)
    return self._content_panels.index(panel)

def _validate_content_position(self, position: int | None, *, allow_end: bool) -> int:
    if position is None:
        return len(self._content_panels)
    if isinstance(position, bool) or not isinstance(position, int):
        raise TypeError("Content panel position must be an integer or None")
    upper = len(self._content_panels) if allow_end else len(self._content_panels) - 1
    if position < 0 or position > upper:
        raise ValueError("Content panel position is outside the menu")
    return position

@staticmethod
def _validate_auto_scroll(mode: AutoScrollMode | None) -> None:
    if mode not in (None, "smart", "strict"):
        raise ValueError("auto_scroll must be 'smart', 'strict', or None")
```

Initialize `_default_auto_scroll` before creating the constructor's primary
panel. `set_content_source()` calls the panel setters when the primary exists;
otherwise it inserts a new primary at position zero with
`_default_auto_scroll`. Export `ContentPanel` from `src/tuiloom/__init__.py` and
add it to `__all__`.

- [ ] **Step 4: Run focused tests and make them GREEN**

Run:

```bash
uv run pytest tests/test_content_panels.py tests/test_public_api.py tests/test_menu_modes.py -q
```

Expected: all selected tests pass; adjust old private-field assertions to use
`content_panels` rather than restoring the removed `_content_source` field.

- [ ] **Step 5: Commit the public model**

```bash
git add src/tuiloom/content_panel.py src/tuiloom/terminal_menu.py src/tuiloom/__init__.py tests/test_content_panels.py tests/test_public_api.py tests/test_menu_modes.py
git commit -m "feat: add stable content panel handles"
```

### Task 2: Route multiple source workers through the event loop

**Files:**
- Modify: `src/tuiloom/event_loop/source_event.py`
- Modify: `src/tuiloom/event_loop/source_worker.py`
- Modify: `src/tuiloom/event_loop/event_loop.py`
- Modify: `src/tuiloom/terminal_menu.py` (`run`, `_create_event_loop`)
- Modify: `tests/event_loop/test_event_loop.py`
- Modify: `tests/event_loop/test_source_worker.py`

- [ ] **Step 1: Write failing parallel-routing tests**

Add tests that use two panels and ensure data and generations stay isolated:

```python
def test_events_are_routed_to_their_own_panels() -> None:
    menu, loop, _, _ = make_loop([None], content=iter(()))
    first = menu.content_panels[0]
    second = menu.add_content_source(iter(()), description="Second")
    loop.add_content_panel(second)

    loop._source_events.put(
        SourceEvent(first, first._generation, "data", "first\n")
    )
    loop._source_events.put(
        SourceEvent(second, second._generation, "data", "second\n")
    )
    loop._drain_source_events()

    assert first._renderer.rendered_content.lines == ["first"]
    assert second._renderer.rendered_content.lines == ["second"]
    loop.close()


def test_replacing_one_panel_does_not_stale_another_panel() -> None:
    menu, loop, _, _ = make_loop([None], content=iter(()))
    first = menu.content_panels[0]
    second = menu.add_content_source(iter(()), description="Second")
    loop.add_content_panel(second)
    first_generation = first._generation
    second_generation = second._generation

    loop.replace_content_panel(first, iter(()))
    loop._source_events.put(SourceEvent(first, first_generation, "data", "stale"))
    loop._source_events.put(
        SourceEvent(second, second_generation, "data", "current\n")
    )
    loop._drain_source_events()

    assert "stale" not in first._renderer.rendered_content.lines
    assert second._renderer.rendered_content.lines == ["current"]
    loop.close()
```

Update `tests/event_loop/test_source_worker.py` so each direct `SourceWorker`
construction passes a real `ContentPanel`, then assert every published event
contains that same handle.

- [ ] **Step 2: Run the tests and verify RED**

```bash
uv run pytest tests/event_loop/test_event_loop.py tests/event_loop/test_source_worker.py -q
```

Expected: failures show that `SourceEvent` has no panel field and `EventLoop`
still owns only one renderer and worker.

- [ ] **Step 3: Tag every source event with its panel**

Change `SourceEvent` to:

```python
from dataclasses import dataclass
from types import TracebackType
from typing import Literal

from tuiloom.content_panel import ContentPanel

type SourceEventKind = Literal["data", "complete", "error"]


@dataclass(frozen=True, slots=True)
class SourceEvent:
    """Carry one panel- and generation-tagged source-worker result."""

    panel: ContentPanel
    generation: int
    kind: SourceEventKind
    value: str | list[str] | None = None
    error: BaseException | None = None
    traceback: TracebackType | None = None
```

Add a `panel: ContentPanel` constructor argument to `SourceWorker`, store it,
and pass it as the first argument in all three `SourceEvent` publication sites.

- [ ] **Step 4: Replace singular event-loop state with panel state**

Change `EventLoop.__init__` to receive the menu and terminal/menu renderers but
no standalone `ContentRenderer`. Initialize every existing panel through this
helper:

```python
def _install_panel_worker(self, panel: ContentPanel) -> None:
    self._generation += 1
    panel._generation = self._generation
    panel._worker = None
    panel._dynamic_in_flight = False
    panel._next_dynamic_at = self._clock()

    if panel._renderer.state == "static":
        return
    source = panel._renderer.source
    if not callable(source) and not hasattr(source, "__next__"):
        raise RuntimeError("Non-static content source cannot be consumed")
    panel._worker = SourceWorker(
        panel=panel,
        generation=panel._generation,
        source=source,
        events=self._source_events,
        notify=self._notify_source,
        description=panel.description,
    )
    panel._worker.start()
```

Add these entry points and use a `dict[ContentPanel, list[SourceEvent]]` inside
`_drain_source_events()`:

```python
def add_content_panel(self, panel: ContentPanel) -> None:
    self._install_panel_worker(panel)
    self.request_render(immediate=True)

def replace_content_panel(
    self, panel: ContentPanel, source: ContentSource
) -> None:
    panel._pending_source = source
    self._generation += 1
    panel._generation = self._generation
    panel._dynamic_in_flight = False
    worker = panel._worker
    if worker is not None and worker.is_alive():
        worker.cancel()
    self.request_render(immediate=True)

@property
def active_panels(self) -> tuple[ContentPanel, ...]:
    active: list[ContentPanel] = []
    for panel in (*self._menu.content_panels, *self._retiring_panels):
        worker = panel._worker
        if worker is None or not worker.is_alive():
            continue
        if panel._renderer.state == "streaming" or panel._dynamic_in_flight:
            active.append(panel)
    return tuple(dict.fromkeys(active))

def _request_dynamic_updates(self) -> None:
    now = self._clock()
    for panel in self._menu.content_panels:
        worker = panel._worker
        if (
            panel._renderer.state != "dynamic"
            or worker is None
            or panel._dynamic_in_flight
            or now < panel._next_dynamic_at
        ):
            continue
        panel._dynamic_in_flight = True
        panel._next_dynamic_at = now + self._FRAME_INTERVAL
        worker.request_dynamic_update()
```

Drain the queue once, discard events whose panel is neither live nor retiring,
discard generation mismatches, and group the survivors by panel. For a
streaming panel, append all string data events in one batch, finish on
`complete`, and apply that panel's auto-scroll. For a dynamic panel, apply only
the final data value in its batch and clear only that panel's
`_dynamic_in_flight`. Process error events after data and re-raise their stored
exception with traceback. Keep the shared bounded queue and wakeup socket.

- [ ] **Step 5: Run focused tests and make them GREEN**

```bash
uv run pytest tests/event_loop -q
```

Expected: all event-loop and source-worker tests pass with two simultaneous
panels and isolated generations.

- [ ] **Step 6: Commit multi-source routing**

```bash
git add src/tuiloom/event_loop src/tuiloom/terminal_menu.py tests/event_loop
git commit -m "feat: route concurrent content panel sources"
```

### Task 3: Support live panel replacement, removal, and safe cleanup

**Files:**
- Modify: `src/tuiloom/event_loop/event_loop.py`
- Modify: `src/tuiloom/terminal_menu.py`
- Modify: `tests/test_content_panels.py`
- Modify: `tests/event_loop/test_event_loop.py`

- [ ] **Step 1: Write failing lifecycle tests**

Add a cancellable blocking iterator fixture and verify mutations do not lose
worker ownership:

```python
def test_active_removal_hides_panel_but_close_joins_retiring_worker() -> None:
    menu, loop, _, _ = make_loop([None], content="primary")
    source = BlockingIterator()
    panel = menu.add_content_source(source, description="Blocking")
    loop.add_content_panel(panel)
    assert source.started.wait(1)

    menu.remove_content_panel(panel)

    assert panel not in menu.content_panels
    assert panel in loop.retiring_panels
    source.release.set()
    loop.close()
    assert panel._worker is not None
    assert not panel._worker.is_alive()


def test_active_replacement_waits_for_old_worker_before_starting_new() -> None:
    menu, loop, _, _ = make_loop([None], content="primary")
    old = BlockingIterator()
    panel = menu.add_content_source(old, description="Work")
    loop.add_content_panel(panel)
    assert old.started.wait(1)

    replacement = iter(["new\n"])
    menu.set_content_panel_source(panel, replacement)
    assert panel._pending_source is replacement
    assert panel._renderer.source is old

    old.release.set()
    loop._progress_panel_transitions()
    assert panel._renderer.source is replacement
    loop.close()


def test_one_panel_error_is_propagated_after_other_workers_are_joined() -> None:
    menu, loop, _, _ = make_loop([None], content="primary")
    blocking = BlockingIterator()
    other = menu.add_content_source(blocking, description="Other")
    loop.add_content_panel(other)
    assert blocking.started.wait(1)
    failed = menu.add_content_source(iter(()), description="Failed")
    loop.add_content_panel(failed)
    error = ValueError("panel failed")
    loop._source_events.put(
        SourceEvent(
            failed,
            failed._generation,
            "error",
            error=error,
            traceback=error.__traceback__,
        )
    )

    with pytest.raises(ValueError, match="panel failed"):
        loop._drain_source_events()
    loop.close()

    assert other._worker is not None
    assert not other._worker.is_alive()
```

Define this cancellable iterator in the test module so cancellation wakes the
blocked `__next__` call:

```python
class BlockingIterator:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.finished = False

    def __iter__(self) -> BlockingIterator:
        return self

    def __next__(self) -> str:
        if self.finished:
            raise StopIteration
        self.started.set()
        self.release.wait(1)
        self.finished = True
        raise StopIteration

    def cancel(self) -> None:
        self.release.set()
```

- [ ] **Step 2: Run lifecycle tests and verify RED**

```bash
uv run pytest tests/test_content_panels.py tests/event_loop/test_event_loop.py -q
```

Expected: failures show no retiring-panel collection or per-panel transition
progression.

- [ ] **Step 3: Implement pending and retiring panel progression**

Add the read-only internal view and transition loop:

```python
@property
def retiring_panels(self) -> tuple[ContentPanel, ...]:
    return tuple(self._retiring_panels)

def retire_content_panel(self, panel: ContentPanel) -> None:
    panel._removed = True
    panel._retiring = True
    panel._pending_source = None
    worker = panel._worker
    if worker is not None and worker.is_alive():
        worker.cancel()
        self._retiring_panels.append(panel)
    elif worker is not None:
        worker.join()
    self.request_render(immediate=True)

def _progress_panel_transitions(self) -> None:
    for panel in tuple(self._retiring_panels):
        worker = panel._worker
        if worker is not None and worker.is_alive():
            continue
        if worker is not None:
            worker.join()
        panel._retiring = False
        self._retiring_panels.remove(panel)

    for panel in self._menu.content_panels:
        source = panel._pending_source
        if source is None:
            continue
        worker = panel._worker
        if worker is not None and worker.is_alive():
            continue
        if worker is not None:
            worker.join()
        panel._pending_source = None
        panel._source = source
        panel._renderer = ContentRenderer(source)
        panel._viewport = None
        self._install_panel_worker(panel)
        self.request_render(immediate=True)
```

Call progression before selector wait. Make `close()` cancel every live and
retiring worker first, then join every one before closing selector and sockets.
On a source exception, let `run()` unwind through this same `close()` path.

- [ ] **Step 4: Run lifecycle and regression tests**

```bash
uv run pytest tests/test_content_panels.py tests/event_loop tests/test_task_exit.py -q
```

Expected: all selected tests pass and no close test leaves a worker alive.

- [ ] **Step 5: Commit lifecycle support**

```bash
git add src/tuiloom/event_loop/event_loop.py src/tuiloom/terminal_menu.py tests/test_content_panels.py tests/event_loop/test_event_loop.py
git commit -m "feat: manage content panel lifecycles"
```

### Task 4: Render equal-height vertical panels with independent focus

**Files:**
- Modify: `src/tuiloom/render/terminal_renderer.py`
- Modify: `src/tuiloom/render/menu_renderer.py`
- Modify: `src/tuiloom/terminal_menu.py`
- Modify: `tests/render/test_terminal_renderer.py`
- Modify: `tests/test_menu_modes.py`

- [ ] **Step 1: Write failing geometry and focus tests**

Add renderer assertions for two labels, equal heights, and separate viewports:

```python
def test_multiple_panels_stack_vertically_with_equal_inner_heights() -> None:
    menu, renderer = make_renderer(content="first")
    second = menu.add_content_source("second", description="Second")
    first = menu.content_panels[0]
    menu.set_content_panel_description(first, "First")

    lines = renderer._compose_frame(32, 20)

    assert sum(line.startswith("╭") for line in lines) == 3
    assert "First" in lines[0]
    second_top = next(index for index, line in enumerate(lines[1:], 1) if "Second" in line)
    first_bottom = next(index for index, line in enumerate(lines) if line.startswith("╰"))
    second_bottom = next(
        index for index, line in enumerate(lines[second_top:], second_top)
        if line.startswith("╰")
    )
    assert first_bottom - 1 == second_bottom - second_top - 1
    assert first._viewport is not None
    assert second._viewport is not None


def test_focus_cycles_and_scrolls_only_the_focused_panel() -> None:
    menu, renderer = make_renderer(content="\n".join(str(i) for i in range(30)))
    second = menu.add_content_source(
        "\n".join(f"b{i}" for i in range(30)), description="Second"
    )
    first = menu.content_panels[0]
    renderer._compose_frame(24, 20)
    assert menu._focused_panel is None

    menu._handle_event(event("tab"))
    assert menu._focused_panel is first
    menu._handle_event(event("down"))
    assert first._viewport is not None and first._viewport.offset_y == 1
    assert second._viewport is not None and second._viewport.offset_y == 0

    menu._handle_event(event("tab"))
    assert menu._focused_panel is second
    menu._handle_event(event("tab"))
    assert menu._focused_panel is None
```

Add a boundary test where the menu plus two panel borders and one inner row per
panel exceed terminal height and expect `Terminal window is too small.`

- [ ] **Step 2: Run renderer tests and verify RED**

```bash
uv run pytest tests/render/test_terminal_renderer.py tests/test_menu_modes.py -q
```

Expected: failures show singular renderer state and binary menu/content focus.

- [ ] **Step 3: Implement vertical composition**

Remove the singular `TerminalRenderer._content_renderer` and `_viewport`.
Derive visible panels from `menu._visible_content_panels()`. Allocate geometry
with:

```python
panel_count = len(panels)
spacing = 1 if self._content_spacing and panel_count else 0
inner_total = terminal_height - menu_height - spacing - 2 * panel_count
if inner_total < panel_count:
    return self._render_terminal_too_small()
base_height, remainder = divmod(inner_total, panel_count)
inner_heights = [
    base_height + (1 if index < remainder else 0)
    for index in range(panel_count)
]
```

For each panel, update or create `panel._viewport`, choose solid borders only
for `menu._focused_panel is panel`, and label the top border when more than one
panel is visible or the exit view is active. Build labels with
`clip_display()`, `display_width()`, and safe padding; never slice raw Unicode or
ANSI strings.

- [ ] **Step 4: Implement focus and per-panel scrolling**

Replace `_focus` with `_focused_panel: ContentPanel | None`, where `None` means
menu focus. Implement:

```python
def _cycle_focus(self) -> None:
    focusable: list[ContentPanel | None] = [None, *self._visible_content_panels()]
    try:
        current = focusable.index(self._focused_panel)
    except ValueError:
        current = 0
    self._focused_panel = focusable[(current + 1) % len(focusable)]

def _scroll_focused_content(
    self, direction: Literal["up", "down", "left", "right"]
) -> None:
    panel = self._focused_panel
    renderer = self._terminal_renderer
    if panel is not None and renderer is not None:
        renderer.scroll_panel(panel, direction)
```

Move smart/strict scroll bookkeeping from the terminal renderer singleton onto
each `ContentPanel`. Ensure removing the focused panel normalizes focus to the
next remaining object. Update `MenuRenderer` focus styling to check
`menu._focused_panel is None`.

- [ ] **Step 5: Run rendering and menu-mode tests**

```bash
uv run pytest tests/render tests/test_menu_modes.py tests/test_commands_and_menu.py -q
```

Expected: stacked panels, independent scroll, resize, and legacy single-panel
tests all pass.

- [ ] **Step 6: Commit multi-panel rendering**

```bash
git add src/tuiloom/render/terminal_renderer.py src/tuiloom/render/menu_renderer.py src/tuiloom/terminal_menu.py tests/render/test_terminal_renderer.py tests/test_menu_modes.py
git commit -m "feat: render focusable vertical content panels"
```

### Task 5: Give captured output its own temporary panel

**Files:**
- Modify: `src/tuiloom/terminal_app.py`
- Modify: `src/tuiloom/terminal_menu.py`
- Modify: `tests/test_output_task.py`
- Modify: `tests/test_task_exit.py`

- [ ] **Step 1: Write failing output-panel tests**

Add coverage that base content remains and the temporary panel has strict
auto-scroll. Import `cast`, `ContentPanel`, and `EventLoop` in the test module:

```python
def test_run_with_output_adds_and_removes_a_temporary_panel() -> None:
    app, menu = make_main()
    base = menu.content_panels[0]
    completed: list[int] = []

    class Loop:
        def __init__(self) -> None:
            self.added: list[ContentPanel] = []

        def add_content_panel(self, panel: ContentPanel) -> None:
            self.added.append(panel)

    loop = Loop()
    menu._event_loop = cast(EventLoop, loop)

    with app._output_capture.install():
        menu.run_with_output(
            lambda: 7,
            on_success=completed.append,
            on_error=lambda error: pytest.fail(str(error)),
            description="Compute",
        )
        session = menu._output_task_session
        output_panel = menu.content_panels[-1]
        assert menu.content_panels == (base, output_panel)
        assert output_panel.description == "Compute"
        assert output_panel.auto_scroll == "strict"
        assert session is not None and session.join(1)
        app._dispatch_output_task_outcome()

    assert completed == [7]
    assert loop.added == [output_panel]
    assert output_panel._remove_when_finished
```

Add a force-stop case asserting the producer and consumer map to one logical
operation panel and callbacks remain discarded. In
`tests/event_loop/test_event_loop.py`, add an event-loop test that sets
`panel._remove_when_finished = True`, publishes its matching `complete` event,
drains events, and asserts the panel is removed from `menu.content_panels` only
after `finish_stream()` preserves the final lines.

- [ ] **Step 2: Run tests and verify RED**

```bash
uv run pytest tests/test_output_task.py tests/test_task_exit.py -q
```

Expected: old code replaces the only renderer instead of adding a panel.

- [ ] **Step 3: Associate output registration with a panel**

Add `panel: ContentPanel | None = None` to the private output registration in
`terminal_app.py`. In `run_with_output()`, start the session, add
`session.iter_output()` as a strict temporary panel, and store the handle on the
registration. Remove `_output_task_previous_auto_scroll` and the old source
replacement/restoration path.

When the producer outcome is dispatched, run callbacks on the UI thread as
today, then retire the temporary panel only after its streaming renderer has
consumed the completion event. Use a private `_remove_when_finished` flag on
the panel and let the event loop retire it after `finish_stream()` so final
captured chunks are not dropped.

- [ ] **Step 4: Preserve abandonment and shutdown guarantees**

Update `_stop_and_quit_output_task()` and `_shutdown_output_task()` to cancel
the producer session and its output view, discard callbacks, and leave joining
to the existing shutdown sequence. Do not treat producer and consumer as two
entries when building logical active panels.

- [ ] **Step 5: Run output and task tests**

```bash
uv run pytest tests/test_output_task.py tests/test_task_exit.py tests/test_terminal_app.py -q
```

Expected: output callbacks, final chunks, abandonment, and temporary-panel
cleanup all pass.

- [ ] **Step 6: Commit output-panel integration**

```bash
git add src/tuiloom/terminal_app.py src/tuiloom/terminal_menu.py src/tuiloom/content_panel.py tests/test_output_task.py tests/test_task_exit.py tests/test_terminal_app.py
git commit -m "feat: render captured output in a temporary panel"
```

### Task 6: Replace numeric exit choices with a reactive menu view

**Files:**
- Create: `src/tuiloom/task_exit.py`
- Modify: `src/tuiloom/terminal_menu.py`
- Modify: `src/tuiloom/render/menu_renderer.py`
- Modify: `src/tuiloom/terminal_app.py`
- Modify: `tests/test_task_exit.py`
- Modify: `tests/render/test_menu_renderer.py`

- [ ] **Step 1: Rewrite exit tests for normal navigation**

Replace numeric helpers with configured action events and assert no footer
mutation. Import `cast`, `ContentPanel`, `EventLoop`, and `SourceWorker`, then
add this fake logical-operation helper:

```python
class FakeWork:
    def __init__(self, description: str) -> None:
        self.description = description
        self.alive = True
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float | None = None) -> bool:
        return not self.alive


def install_fake_active_panel(
    menu: TerminalMenu, *, description: str
) -> FakeWork:
    panel = menu.add_content_source("last output", description=description)
    work = FakeWork(description)
    panel._worker = cast(SourceWorker, work)

    class Loop:
        @property
        def active_panels(self) -> tuple[ContentPanel, ...]:
            return (panel,) if work.alive else ()

        @property
        def retiring_panels(self) -> tuple[ContentPanel, ...]:
            return ()

    menu._event_loop = cast(EventLoop, Loop())
    return work


def press(menu: TerminalMenu, key: str, text: str | None = None) -> None:
    menu._handle_event(InputEvent(KeyBinding(key), text))


def test_exit_choices_use_arrows_enter_and_leave_screen_context_unchanged() -> None:
    _, menu = make_main()
    work = install_fake_active_panel(menu, description="Streaming")
    menu.screen_context.title = "Main"
    menu.screen_context.message = "Previous"

    menu.stop()

    assert menu._task_exit is not None
    assert menu._task_exit.visible_title(1) == "Operation in progress"
    assert menu._task_exit.rows == ("Force quit", "Wait and quit", "Cancel")
    assert menu.screen_context.title == "Main"
    assert menu.screen_context.message == "Previous"

    press(menu, "down")
    press(menu, "enter")
    assert menu._task_exit.mode == "waiting"
    assert menu._task_exit.rows == ("Cancel",)
    assert not work.cancelled


def test_numeric_exit_shortcuts_are_not_accepted() -> None:
    _, menu = make_main()
    install_fake_active_panel(menu, description="Work")
    menu.stop()

    for key in ("1", "2", "0"):
        press(menu, key, key)

    assert menu._task_exit is not None
    assert menu._task_exit.mode == "choice"
```

Add tests for back-as-cancel, state restoration, force non-interactivity,
singular/plural title changes, and automatic stop when active work reaches zero:

```python
def test_back_cancels_and_restores_focus_and_selection() -> None:
    _, menu = make_main()
    install_fake_active_panel(menu, description="Work")
    menu._selected_index = len(menu.commands)
    previous_selection = menu._selected_index
    menu.stop()
    press(menu, "escape")
    assert menu._task_exit is None
    assert menu._focused_panel is None
    assert menu._selected_index == previous_selection
    assert menu._running


def test_choice_view_tracks_completion_and_quits_at_zero() -> None:
    _, menu = make_main()
    first_panel = menu.add_content_source("first", description="First")
    second = menu.add_content_source("second", description="Second")
    first = FakeWork("First")
    second_work = FakeWork("Second")
    first_panel._worker = cast(SourceWorker, first)
    second._worker = cast(SourceWorker, second_work)

    class Loop:
        @property
        def active_panels(self) -> tuple[ContentPanel, ...]:
            return tuple(
                panel
                for panel in (first_panel, second)
                if panel._worker is not None and panel._worker.is_alive()
            )

        @property
        def retiring_panels(self) -> tuple[ContentPanel, ...]:
            return ()

    menu._event_loop = cast(EventLoop, Loop())
    menu.stop()
    assert menu._task_exit is not None
    assert menu._task_exit.visible_title(2) == "Operations in progress"

    second_work.alive = False
    assert not menu._tick_task_exit(0.0)
    assert menu._task_exit.visible_title(1) == "Operation in progress"

    first.alive = False
    assert menu._tick_task_exit(0.1)
    assert not menu._running
```

Repeat the live-count assertions after selecting Wait and Force. In the Force
case, add a third panel after selection, tick once, and assert its worker's
`cancelled` flag becomes true; this proves new work is incorporated and
immediately cancelled.

- [ ] **Step 2: Run exit tests and verify RED**

```bash
uv run pytest tests/test_task_exit.py tests/render/test_menu_renderer.py -q
```

Expected: failures show footer messages, numeric dispatch, and no temporary
menu projection.

- [ ] **Step 3: Add the internal exit-view state**

Create `src/tuiloom/task_exit.py`:

```python
from dataclasses import dataclass
from typing import Literal

from tuiloom.content_panel import ContentPanel

type TaskExitMode = Literal["choice", "waiting", "stopping"]


@dataclass(slots=True)
class TaskExitView:
    mode: TaskExitMode
    selected_index: int
    previous_focus: ContentPanel | None
    previous_selected_index: int
    wait_started_at: float
    wait_phase: int = -1

    @property
    def rows(self) -> tuple[str, ...]:
        if self.mode == "choice":
            return ("Force quit", "Wait and quit", "Cancel")
        if self.mode == "waiting":
            return ("Cancel",)
        return ()

    def visible_title(self, operation_count: int) -> str:
        plural = operation_count != 1
        if self.mode == "stopping":
            return "Stopping operations..." if plural else "Stopping operation..."
        return "Operations in progress" if plural else "Operation in progress"

    def move(self, delta: int) -> None:
        rows = self.rows
        if rows:
            self.selected_index = (self.selected_index + delta) % len(rows)
```

- [ ] **Step 4: Project exit state through `MenuRenderer`**

Make `_MenuState.exit_label` optional. When `_task_exit` exists, snapshot its
computed title, rows, selection, and no footer message; suppress normal commands,
text, alert/input rows, and the automatic Back/Quit row. Do not assign to any
`ScreenContext` field.

Add `TerminalMenu._visible_content_panels()` so ordinary mode returns live menu
panels and exit mode returns the current active logical panels, including
retiring workers. Apply wait animation to derived border labels rather than
mutating `ContentPanel.description`.

- [ ] **Step 5: Dispatch keymap actions and react to live work**

In `_handle_event`, resolve the configured keymap action before exit dispatch.
For choice mode, up/down move, activate dispatches the selected row, focus
cycles through visible operation panels, and back cancels. Waiting exposes only
Cancel. Stopping ignores input.

Replace `_tick_task_exit()` with live recomputation on every state check:

```python
def _tick_task_exit(self, now: float) -> bool:
    view = self._task_exit
    if view is None:
        return False
    active = self._current_exit_panels()
    if not active:
        self._task_exit = None
        self._stop_immediately()
        return True
    if view.mode == "stopping":
        for panel in active:
            self._cancel_panel_operation(panel)
        return True
    if view.mode != "waiting":
        return False
    phase = int((now - view.wait_started_at) / 0.4) % 3 + 1
    if phase == view.wait_phase:
        return False
    view.wait_phase = phase
    return True
```

Force mode must also cancel any operation that starts after the selection.
Waiting mode must allow callbacks and new work, and quit only after their active
set is empty. Remove the now-unnecessary output registration
`exit_when_complete` and `exit_menu` fields from `terminal_app.py`.

- [ ] **Step 6: Run exit, renderer, and callback tests**

```bash
uv run pytest tests/test_task_exit.py tests/render/test_menu_renderer.py tests/test_terminal_app.py -q
```

Expected: all exit states are navigable without numeric shortcuts, active
panels remain reactive, and screen context values remain untouched.

- [ ] **Step 7: Commit the exit menu**

```bash
git add src/tuiloom/task_exit.py src/tuiloom/terminal_menu.py src/tuiloom/render/menu_renderer.py src/tuiloom/terminal_app.py tests/test_task_exit.py tests/render/test_menu_renderer.py tests/test_terminal_app.py
git commit -m "feat: add reactive task exit menu"
```

### Task 7: Verify real terminal behavior and the full non-documentation API

**Files:**
- Modify: `tests/test_pty.py`
- Modify: affected tests under `tests/`

- [ ] **Step 1: Add a PTY multi-panel scenario**

Add a child program that creates two static panels and waits for Escape. Capture
its frame and assert both labels, both payloads, and the normal menu title:

```python
def test_pty_renders_two_labeled_content_panels() -> None:
    script = """
from tuiloom import ScreenContext, TerminalApp, TerminalMenu

app = TerminalApp("App")
menu = TerminalMenu(app, ScreenContext("main", "Main"), content_source="alpha")
menu.set_content_panel_description(menu.content_panels[0], "Alpha")
menu.add_content_source("beta", description="Beta")
app.set_main_menu(menu)
app.run()
print("RESTORED")
"""
    process, master = _spawn(script)
    initial = _read_until(master, process, b"Beta")
    os.write(master, b"\x1b")
    final = initial + _finish(process, master)
    assert b"Alpha" in final
    assert b"alpha" in final
    assert b"Beta" in final
    assert b"beta" in final
    assert b"Main" in final
```

- [ ] **Step 2: Run the PTY test and verify RED, then GREEN**

Run the new test:

```bash
uv run pytest tests/test_pty.py -q
```

Expected first run: FAIL because the existing captured frame has one unlabeled
content box. After completing the production behavior from Tasks 1–6, expected
final run: PASS.

- [ ] **Step 3: Run all non-documentation quality checks**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src tests
uv run pytest --cov=tuiloom --cov-report=term-missing
```

Expected: Ruff and mypy exit 0; pytest passes with coverage at or above 90%.
Fix only issues introduced by this feature, rerunning the failing command after
each correction.

- [ ] **Step 4: Commit integration adjustments**

```bash
git add tests src
git commit -m "test: verify multi-content terminal integration"
```

If `git status --short` shows no tracked changes after Step 3, skip this empty
commit.

### Task 8: Mandatory public API review checkpoint

**Files:**
- Read: `src/tuiloom/content_panel.py`
- Read: `src/tuiloom/terminal_menu.py`
- Read: `src/tuiloom/__init__.py`
- Do not modify: `README.md`

- [ ] **Step 1: Produce the exact review artifact**

Extract signatures from the implemented code:

```bash
uv run python - <<'PY'
from inspect import signature
from tuiloom import ContentPanel, TerminalMenu

for name in (
    "add_content_source",
    "set_content_panel_source",
    "set_content_panel_description",
    "set_content_panel_auto_scroll",
    "move_content_panel",
    "remove_content_panel",
    "set_content_source",
):
    print(f"TerminalMenu.{name}{signature(getattr(TerminalMenu, name))}")
for name in ("description", "position", "auto_scroll"):
    print(f"ContentPanel.{name}: property")
PY
```

Present that exact output, this usage example, and the verified compatibility
behavior to the user:

```python
logs = menu.add_content_source(
    log_stream,
    description="Downloading",
    auto_scroll="strict",
)
metrics = menu.add_content_source(get_metrics, description="Indexing")

menu.move_content_panel(metrics, 0)
menu.set_content_panel_description(logs, "Downloading model")
menu.remove_content_panel(metrics)
```

- [ ] **Step 2: Stop and obtain explicit approval**

Do not edit `README.md`, release metadata, or documentation prose. Wait until
the user explicitly approves the implemented names, signatures, example, and
legacy behavior. If the user requests API changes, add failing API tests first,
implement them, rerun Task 7 Step 3, and repeat this checkpoint.

### Task 9: Document the approved API and behavior

**Files:**
- Modify: `README.md`
- Modify: `tests/test_public_api.py` only if the approved API changed at Task 8

- [ ] **Step 1: Update conceptual content-source documentation**

After approval, update the README content-source section with the exact example
from Task 8. Explain ordered vertical stacking, equal height, panel labels,
focus cycling, independent scroll/auto-scroll, dynamic add/remove, and the
single-source compatibility behavior.

- [ ] **Step 2: Update safe-shutdown documentation**

Replace the numeric prompt and footer description with:

```text
Operation in progress / Operations in progress

Force quit
Wait and quit
Cancel
```

Document arrow navigation, Enter activation, Back-as-Cancel, the waiting-only
Cancel row, non-interactive stopping state, live operation removal, singular
and plural updates, and automatic exit when no blocker remains.

- [ ] **Step 3: Update the API reference and legacy message status**

Add `ContentPanel` to the public import list and document every approved
property and `TerminalMenu` method signature. Mark `TASK_EXIT_CHOICES`,
`TASK_WAITING`, and `TASK_STOPPING` as retained compatibility keys that no
longer control the automatic exit UI.

- [ ] **Step 4: Check documentation consistency**

```bash
rg -n "1: Stop and quit|2: Wait and quit|0: Cancel|TASK_EXIT_CHOICES|ContentPanel|add_content_source" README.md
uv run pytest tests/test_public_api.py -q
git diff --check
```

Expected: no old numeric-choice prose remains; compatibility message-key
mentions are clearly marked; the public API test passes; diff check is clean.

- [ ] **Step 5: Commit approved documentation**

```bash
git add README.md tests/test_public_api.py
git commit -m "docs: document multi-content panels and exit menu"
```

### Task 10: Final verification and review

**Files:**
- Verify all tracked feature files

- [ ] **Step 1: Run the complete project gate**

```bash
make check
uv build
uv run twine check dist/*
```

Expected: lint, format check, strict typing, all tests, coverage threshold,
package build, and distribution metadata checks pass.

- [ ] **Step 2: Inspect the final diff and commits**

```bash
git status --short
git diff --check HEAD~8..HEAD
git log --oneline --decorate -12
```

Expected: no unintended tracked changes, no whitespace errors, and separate
commits for model, routing, lifecycle, rendering, output integration, exit UI,
integration tests, and approved documentation. `.superpowers/` may remain as an
untracked visual-companion artifact and must not be included in feature commits.

- [ ] **Step 3: Request code review**

Invoke the `requesting-code-review` skill and review the implementation against
`docs/superpowers/specs/2026-08-29-multi-content-exit-menu-design.md`. Address
every correctness issue with a failing regression test before changing
production code.

- [ ] **Step 4: Re-run the complete gate after review fixes**

```bash
make check
uv build
uv run twine check dist/*
```

Expected: every command exits 0 after review changes.
