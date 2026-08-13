# Event-Driven Rendering Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Tuiloom responsive while synchronous content sources are slow, and eliminate repeated rendering work for unchanged terminal state.

**Architecture:** A selectable UI event loop owns terminal state while a daemon source worker consumes synchronous iterators or dynamic callables. Source events cross a bounded queue, content updates are batched and versioned, and menu and viewport caches render only dirty state at a maximum of 60 frames per second.

**Tech Stack:** Python 3.12, standard-library `selectors`, `socket`, `queue`, and `threading`, `wcwidth >= 0.8`, pytest, mypy strict, Ruff

---

## File Structure

- Create `src/tuiloom/event_loop/__init__.py`: package marker for the internal event-loop implementation.
- Create `src/tuiloom/event_loop/source_event.py`: typed data, completion, and failure events sent by source workers.
- Create `src/tuiloom/event_loop/source_worker.py`: daemon worker, bounded queue publication, cancellation, and selectable wakeup channel.
- Create `src/tuiloom/event_loop/event_loop.py`: input/source multiplexing, batching, frame scheduling, and lightweight periodic checks.
- Create `tests/event_loop/__init__.py`: event-loop test package marker.
- Create `tests/event_loop/test_source_worker.py`: worker lifecycle, queue bounds, cancellation, and traceback propagation.
- Create `tests/event_loop/test_event_loop.py`: deterministic input draining, batching, frame deadlines, idle behavior, and errors.
- Modify `src/tuiloom/render/rendered_content.py`: add a content revision used by render caches.
- Modify `src/tuiloom/render/content_renderer.py`: stop consuming sources in `update()`, accept batches, track revisions, and incrementally normalize streams.
- Modify `tests/render/test_content_renderer.py`: replace synchronous iterator-consumption assumptions with batching and incremental-boundary tests.
- Modify `src/tuiloom/render/menu_renderer.py`: cache rendered menu output from a visible-state snapshot.
- Modify `tests/render/test_menu_renderer.py`: verify cache hits and invalidation for every mutable screen field.
- Modify `src/tuiloom/render/viewport.py`: cache rendered viewport output by content revision, dimensions, and offsets.
- Modify `tests/render/test_viewport.py`: verify cache hits and scroll/content invalidation.
- Modify `src/tuiloom/render/terminal_renderer.py`: expose cheap dirty checks, skip unchanged composition, and retain terminal-boundary sanitation.
- Modify `tests/render/test_terminal_renderer.py`: verify unchanged rendering avoids menu and viewport work.
- Modify `src/tuiloom/input_handler/input_handler.py`: expose its readable descriptor and drain already buffered events without fixed sleeps.
- Modify `tests/test_terminal_menu_input.py`: verify all immediately available input is handled in one loop turn.
- Modify `src/tuiloom/terminal_menu.py`: replace the fixed render/sleep loop with the internal event loop and manage content-source replacement.
- Modify `tests/test_terminal_app.py` and `tests/test_terminal_menu_input.py`: cover integration, replacement, error cleanup, and public behavior.
- Create `benchmarks/rendering.py`: reproducible streaming and unchanged-frame benchmarks outside the correctness suite.
- Modify `README.md`: document non-blocking synchronous streams and the 60 FPS batching behavior.

Existing uncommitted edits in `src/tuiloom/__init__.py`, `src/tuiloom/terminal_menu.py`, and `tests/test_public_api.py` belong to the user. Preserve them and stage only task-specific hunks at every commit.

### Task 1: Add typed source events and a bounded worker

**Files:**
- Create: `src/tuiloom/event_loop/__init__.py`
- Create: `src/tuiloom/event_loop/source_event.py`
- Create: `src/tuiloom/event_loop/source_worker.py`
- Create: `tests/event_loop/__init__.py`
- Create: `tests/event_loop/test_source_worker.py`

- [ ] **Step 1: Write failing worker tests**

Create the two package marker files as empty files. Create `tests/event_loop/test_source_worker.py` with:

```python
from collections.abc import Iterator
from queue import Queue
from threading import Event

from tuiloom.event_loop.source_event import SourceEvent
from tuiloom.event_loop.source_worker import SourceWorker


def test_iterator_worker_publishes_data_and_completion() -> None:
    events: Queue[SourceEvent] = Queue(maxsize=8)
    wakeups: list[None] = []
    worker = SourceWorker(
        generation=4,
        source=iter(["first", "second"]),
        events=events,
        notify=lambda: wakeups.append(None),
    )

    worker.start()
    worker.join(timeout=1)

    received = [events.get_nowait(), events.get_nowait(), events.get_nowait()]
    assert [(event.kind, event.value) for event in received] == [
        ("data", "first"),
        ("data", "second"),
        ("complete", None),
    ]
    assert all(event.generation == 4 for event in received)
    assert len(wakeups) == 3


def test_worker_transports_failure_with_traceback() -> None:
    def fail() -> Iterator[str]:
        yield "before"
        raise ValueError("broken source")

    events: Queue[SourceEvent] = Queue(maxsize=8)
    worker = SourceWorker(1, fail(), events, lambda: None)

    worker.start()
    worker.join(timeout=1)
    events.get_nowait()
    failure = events.get_nowait()

    assert failure.kind == "error"
    assert isinstance(failure.error, ValueError)
    assert failure.traceback is not None


def test_cancelled_worker_stops_publishing_after_blocked_next_returns() -> None:
    entered = Event()
    release = Event()

    def blocked() -> Iterator[str]:
        entered.set()
        release.wait(timeout=1)
        yield "stale"

    events: Queue[SourceEvent] = Queue(maxsize=8)
    worker = SourceWorker(1, blocked(), events, lambda: None)
    worker.start()
    assert entered.wait(timeout=1)

    worker.cancel()
    release.set()
    worker.join(timeout=1)

    assert events.empty()
```

- [ ] **Step 2: Run the worker tests and verify RED**

Run: `uv run pytest -q tests/event_loop/test_source_worker.py`

Expected: collection fails because `tuiloom.event_loop.source_event` does not exist.

- [ ] **Step 3: Implement the source event value object**

Create `src/tuiloom/event_loop/source_event.py` with:

```python
from dataclasses import dataclass
from types import TracebackType
from typing import Literal

type SourceEventKind = Literal["data", "complete", "error"]


@dataclass(frozen=True, slots=True)
class SourceEvent:
    """Carry one generation-tagged result from a content source worker."""

    generation: int
    kind: SourceEventKind
    value: str | list[str] | None = None
    error: BaseException | None = None
    traceback: TracebackType | None = None
```

- [ ] **Step 4: Implement iterator consumption and cancellation**

Create `src/tuiloom/event_loop/source_worker.py` with a `SourceWorker` whose public surface is:

```python
from collections.abc import Callable, Iterator
from queue import Full, Queue
from threading import Event, Thread

from tuiloom.event_loop.source_event import SourceEvent


class SourceWorker:
    """Consume one synchronous content source outside the UI thread."""

    def __init__(
        self,
        generation: int,
        source: Iterator[str] | Callable[[], str | list[str]],
        events: Queue[SourceEvent],
        notify: Callable[[], None],
    ) -> None:
        self.generation = generation
        self.source = source
        self.events = events
        self._notify = notify
        self._cancelled = Event()
        self._dynamic_requested = Event()
        self._thread = Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def cancel(self) -> None:
        self._cancelled.set()
        self._dynamic_requested.set()

    def request_dynamic_update(self) -> None:
        if callable(self.source):
            self._dynamic_requested.set()
```

Implement `_run()` with separate explicit `_run_iterator()` and `_run_dynamic()` methods. `_run_iterator()` iterates until cancellation, validates every chunk as `str`, and publishes a final `complete` event. `_run_dynamic()` waits on `_dynamic_requested`, clears it before each call, and never runs two calls concurrently. In `_run_iterator()`'s `finally`, call the iterator's `close()` method when it exists; if cancellation arrived during a blocked `next()`, this happens immediately after that call returns.

Implement `_publish()` with `Queue.put(..., timeout=0.05)` inside a loop that checks `_cancelled` after every `Full`. Call `_notify()` only after the event enters the queue. On failure, publish `SourceEvent(..., kind="error", error=error, traceback=error.__traceback__)`. Do not publish completion or error after cancellation.

- [ ] **Step 5: Run the worker tests and verify GREEN**

Run: `uv run pytest -q tests/event_loop/test_source_worker.py`

Expected: all three tests pass.

- [ ] **Step 6: Commit the worker foundation**

```bash
git add src/tuiloom/event_loop tests/event_loop
git commit -m "feat: consume content sources outside UI thread"
```

### Task 2: Make streamed content batched, versioned, and incremental

**Files:**
- Modify: `src/tuiloom/render/rendered_content.py`
- Modify: `src/tuiloom/render/content_renderer.py`
- Modify: `tests/render/test_content_renderer.py`

- [ ] **Step 1: Replace iterator-pull tests with failing batch tests**

Keep the static validation tests. Replace `test_dynamic_content_is_replaced_on_each_update`, `test_streamed_content_accumulates_chunks_and_finishes`, and `test_invalid_streamed_chunk_raises_type_error` with event-driven update coverage:

```python
def test_streamed_content_changes_only_when_chunks_are_appended() -> None:
    renderer = ContentRenderer(iter(["unused"]))

    initial = renderer.update()
    assert initial.lines == [""]
    assert initial.revision == 0

    renderer.append_stream_batch(["first", "\nsecond"])
    changed = renderer.update()

    assert changed.lines == ["first", "second"]
    assert changed.revision == 1
    assert renderer.update().revision == 1


def test_stream_batch_preserves_split_ansi_and_unicode_tail() -> None:
    renderer = ContentRenderer(iter(()))

    renderer.append_stream_batch(["\x1b[35", "mA👨‍"])
    renderer.append_stream_batch(["👩‍👧", "\nsecond"])
    content = renderer.update()

    assert "\x1b[35m" in content.lines[0]
    assert "👨‍👩‍👧" in content.lines[0]
    assert content.lines[1].startswith("\x1b[35m")


def test_stream_revision_changes_once_per_nonempty_batch() -> None:
    renderer = ContentRenderer(iter(()))

    renderer.append_stream_batch(["a", "b", "c"])
    first_revision = renderer.update().revision
    renderer.append_stream_batch([])

    assert first_revision == 1
    assert renderer.update().revision == first_revision


def test_stream_completion_marks_content_finished() -> None:
    renderer = ContentRenderer(iter(()))
    renderer.append_stream_batch(["done"])

    renderer.finish_stream()

    assert renderer.update().finished is True


def test_dynamic_content_is_replaced_only_when_result_is_delivered() -> None:
    renderer = ContentRenderer(lambda: "unused")

    assert renderer.update().lines == [""]

    renderer.replace_dynamic_content("first")
    assert renderer.update().lines == ["first"]

    renderer.replace_dynamic_content("second\nline")
    assert renderer.update().lines == ["second", "line"]


def test_invalid_streamed_batch_chunk_raises_type_error() -> None:
    renderer = ContentRenderer(iter(()))

    with pytest.raises(TypeError, match="chunks must be str"):
        renderer.append_stream_batch([42])  # type: ignore[list-item]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest -q tests/render/test_content_renderer.py`

Expected: failures report missing `RenderedContent.revision` and missing `append_stream_batch()`.

- [ ] **Step 3: Add content revisions**

Change `RenderedContent` to:

```python
@dataclass
class RenderedContent:
    """Store normalized content lines, dimensions, and completion state."""

    lines: list[str]
    width: int
    height: int
    finished: bool
    revision: int = 0
```

The default preserves existing direct constructor calls in viewport tests.

- [ ] **Step 4: Separate source ownership from content updates**

In `ContentRenderer`, keep source classification in `__init__`, but remove `_update = _handle_streaming_state`. `update()` must become a read-only return of `rendered_content` for static and streaming sources. Dynamic results enter through a new `replace_dynamic_content(content)` method rather than by calling user code from `update()`.

Add this public internal surface:

```python
def append_stream_batch(self, chunks: list[str]) -> None:
    """Append one validated batch and update streaming content once."""

def replace_dynamic_content(self, content: str | list[str]) -> None:
    """Replace dynamic content when its latest value changed."""

def finish_stream(self) -> None:
    """Commit the stream tail and mark streaming content complete."""
```

Use a focused private `_StreamingTextBuffer` in the same module. It stores completed normalized line fragments, the small unstable raw suffix of the active line, the active propagated SGR prefix, completed-line widths, and the active-line width. Its surface is:

```python
class _StreamingTextBuffer:
    def append(self, chunks: list[str]) -> tuple[list[str], int]:
        """Append chunks and return current normalized lines and width."""

    def finish(self) -> tuple[list[str], int]:
        """Commit the final mutable tail and return the final geometry."""
```

Join each incoming batch once. Feed it through `wcwidth.iter_sequences()` and `wcwidth.iter_graphemes()`. Move complete safe SGR sequences and finalized graphemes into line-fragment lists immediately; retain only an incomplete terminal sequence or the final potentially extendable grapheme as the unstable raw suffix. A newline commits the current fragment list and starts the next logical line.

Derive the style prefix after each SGR transition with `wcwidth.propagate_sgr([active_style + sequence, ""])[1]`, removing only its final `RESET_SGR`. Materialize a display line by joining already-normalized fragments and normalizing only the unstable suffix. Never pass the complete accumulated active line back through `normalize_line()`. Maintain widths by adding finalized grapheme widths and recalculating only the unstable suffix. This keeps sanitation and Unicode normalization work amortized linear even when a generated response contains no newline.

Increment `RenderedContent.revision` once after a nonempty stream batch. For dynamic content, compare normalized lines and dimensions and increment only when they differ. Mark a stream finished without incrementing its visual revision if finishing does not alter visible lines.

- [ ] **Step 5: Run content-renderer tests and verify GREEN**

Run: `uv run pytest -q tests/render/test_content_renderer.py`

Expected: all content-renderer tests pass.

- [ ] **Step 6: Add a normalization-work regression test**

Monkeypatch the private fragment-normalization helper with a counting wrapper. Append 4,000 one-character chunks without newlines in batches of 64 and assert no call receives text longer than the final unstable grapheme or incomplete terminal sequence. Then append 200 newline-terminated lines and assert committed lines are never normalized again by later batches.

Run: `uv run pytest -q tests/render/test_content_renderer.py`

Expected before tightening the implementation: the call-count assertion fails. Expected after using committed lines and a mutable tail: it passes.

- [ ] **Step 7: Commit batched content rendering**

```bash
git add src/tuiloom/render/rendered_content.py src/tuiloom/render/content_renderer.py tests/render/test_content_renderer.py
git commit -m "perf: normalize streamed content incrementally"
```

### Task 3: Cache menu and viewport rendering

**Files:**
- Modify: `src/tuiloom/render/menu_renderer.py`
- Modify: `tests/render/test_menu_renderer.py`
- Modify: `src/tuiloom/render/viewport.py`
- Modify: `tests/render/test_viewport.py`

- [ ] **Step 1: Write failing menu-cache tests**

Append to `tests/render/test_menu_renderer.py`:

```python
def test_unchanged_screen_context_reuses_cached_menu_render() -> None:
    context = make_context(width=20)
    renderer = MenuRenderer(context)

    first = renderer.render()
    second = renderer.render()

    assert second is first


def test_changed_screen_context_invalidates_cached_menu_render() -> None:
    context = make_context(width=20, message="first")
    renderer = MenuRenderer(context)
    first = renderer.render()

    context.message = "second"
    renderer.update_screen_context(context)

    assert renderer.render() != first
```

Run: `uv run pytest -q tests/render/test_menu_renderer.py`

Expected: the identity assertion fails because `render()` creates a new string.

- [ ] **Step 2: Implement a visible menu-state snapshot**

Add an immutable `_MenuState` dataclass containing `app_name`, `title`, displayed command key/label tuples, `text`, `two_columns`, `message`, `alert`, `prompt`, and requested width. Add a read-only integer `revision` property initialized to zero. `update_screen_context()` constructs the new snapshot, returns early when it equals the previous snapshot, and otherwise copies fields, recalculates width, increments the revision, and clears `_cached_render`.

Change `render()` to return `_cached_render` when present. Move current composition into `_render_menu()`, cache that returned string, and return the exact cached object on later calls.

Run: `uv run pytest -q tests/render/test_menu_renderer.py`

Expected: all menu-renderer tests pass.

- [ ] **Step 3: Write failing viewport-cache tests**

Append to `tests/render/test_viewport.py`:

```python
def test_unchanged_viewport_reuses_cached_render() -> None:
    viewport = Viewport(content(), width=4, height=2)

    first = viewport.render()
    second = viewport.render()

    assert second is first


def test_content_revision_invalidates_cached_viewport() -> None:
    rendered = content()
    viewport = Viewport(rendered, width=4, height=2)
    first = viewport.render()
    rendered.lines[0] = "changed"
    rendered.width = 7
    rendered.revision += 1

    assert viewport.render() != first
```

Run: `uv run pytest -q tests/render/test_viewport.py`

Expected: the identity assertion fails because `render()` creates a new string.

- [ ] **Step 4: Cache viewport output by a complete render key**

Add:

```python
type ViewportRenderKey = tuple[int, int, int, int, int]
```

Store `_cached_key: ViewportRenderKey | None` and `_cached_render: str | None`. At the start of `render()`, clamp offsets, construct `(content.revision, width, height, offset_x, offset_y)`, and return the cached string when the key matches. Cache the newly joined string otherwise.

The existing mutable `content`, `width`, and `height` attributes remain compatible. Scroll methods need no manual cache clearing because offsets are part of the key.

Run: `uv run pytest -q tests/render/test_viewport.py`

Expected: all viewport tests pass.

- [ ] **Step 5: Commit renderer caches**

```bash
git add src/tuiloom/render/menu_renderer.py tests/render/test_menu_renderer.py src/tuiloom/render/viewport.py tests/render/test_viewport.py
git commit -m "perf: cache unchanged menu and viewport renders"
```

### Task 4: Add the selectable source channel and event loop

**Files:**
- Create: `src/tuiloom/event_loop/event_loop.py`
- Modify: `src/tuiloom/event_loop/source_worker.py`
- Modify: `src/tuiloom/input_handler/input_handler.py`
- Create: `tests/event_loop/test_event_loop.py`

- [ ] **Step 1: Write failing deterministic event-loop tests**

Create fakes in `tests/event_loop/test_event_loop.py` for a monotonic clock, input handler, terminal renderer, menu renderer, and selector. Cover these exact behaviors:

```python
def test_loop_drains_every_available_input_event() -> None:
    input_handler = FakeInputHandler([char("1"), char("2"), None])
    loop = make_loop(input_handler=input_handler)

    loop.run_once()

    assert loop.input_buffer == "12"
    assert input_handler.poll_calls == 3


def test_loop_batches_all_current_source_chunks() -> None:
    loop, source_events, content_renderer = make_streaming_loop()
    source_events.put(SourceEvent(1, "data", "a"))
    source_events.put(SourceEvent(1, "data", "b"))
    source_events.put(SourceEvent(1, "data", "c"))

    loop.run_once()

    assert content_renderer.batches == [["a", "b", "c"]]


def test_loop_does_not_render_clean_state_before_deadline() -> None:
    loop, clock, terminal_renderer = make_scheduled_loop()
    loop.request_render()
    loop.run_once()
    clock.advance(0.005)

    loop.run_once()

    assert terminal_renderer.render_calls == 1


def test_source_error_is_raised_with_worker_traceback() -> None:
    loop, source_events, _ = make_streaming_loop()
    error = ValueError("broken source")
    source_events.put(
        SourceEvent(1, "error", error=error, traceback=error.__traceback__)
    )

    with pytest.raises(ValueError, match="broken source"):
        loop.run_once()
```

The fakes must expose only the methods used by `EventLoop`; do not patch real time or open a real terminal.

- [ ] **Step 2: Run event-loop tests and verify RED**

Run: `uv run pytest -q tests/event_loop/test_event_loop.py`

Expected: collection fails because `tuiloom.event_loop.event_loop` does not exist.

- [ ] **Step 3: Expose the input descriptor**

Add to `InputHandler`:

```python
def fileno(self) -> int:
    """Return the terminal descriptor watched by the application event loop."""
    return self.fd
```

Keep `poll()` non-blocking and backward compatible.

- [ ] **Step 4: Implement the event loop**

Create `EventLoop` with these constructor dependencies so tests can supply fakes:

```python
class EventLoop:
    """Coordinate input, content sources, and frame scheduling for one menu."""

    _FRAME_INTERVAL = 1 / 60
    _STATE_CHECK_INTERVAL = 0.1

    def __init__(
        self,
        menu: TerminalMenu,
        input_handler: InputHandler,
        menu_renderer: MenuRenderer,
        terminal_renderer: TerminalRenderer,
        content_renderer: ContentRenderer,
        *,
        clock: Callable[[], float] = monotonic,
        selector_factory: Callable[[], BaseSelector] = DefaultSelector,
    ) -> None:
```

The implementation must have small explicit methods named `_drain_input()`, `_drain_source_events()`, `_handle_source_event()`, `_request_dynamic_update()`, `_render_if_due()`, `_get_wait_timeout()`, and `_check_visible_state()`.

Use a non-blocking `socketpair()` as the source wakeup channel. Register the input descriptor and wakeup reader with the selector. Coalesce wake bytes: `_notify_source()` attempts to send one byte and ignores `BlockingIOError`; `_drain_wakeup()` reads until `BlockingIOError`.

Keep a `Queue[SourceEvent](maxsize=256)`, a generation counter, and the active `SourceWorker`. Implement `install_source(source: ContentSource)`: it cancels the old worker, increments the generation, clears stale queued events, creates and installs a new `ContentRenderer`, and starts a worker only for iterator or callable state. The constructor calls the same private installation path for its initial `content_renderer.source` without replacing the renderer object supplied by `TerminalMenu`.

`run_once()` performs this order:

1. select with `_get_wait_timeout()`;
2. drain input if readable;
3. drain wake bytes and source events if readable;
4. request a dynamic refresh when due and none is in flight;
5. compare lightweight menu state and terminal size when due;
6. render dirty state when the frame deadline permits.

When handling data events, combine adjacent `str` values for a streaming source and call `append_stream_batch()` exactly once. For dynamic sources, pass the latest result to `replace_dynamic_content()` and discard older queued results from the same batch. On completion call `finish_stream()`. Raise failures with `raise event.error.with_traceback(event.traceback)`.

`close()` cancels the active worker, closes the selector and both wakeup sockets, and never performs an unbounded join.

- [ ] **Step 5: Run event-loop tests and verify GREEN**

Run: `uv run pytest -q tests/event_loop/test_event_loop.py tests/event_loop/test_source_worker.py`

Expected: all event-loop and worker tests pass.

- [ ] **Step 6: Commit the event loop**

```bash
git add src/tuiloom/event_loop src/tuiloom/input_handler/input_handler.py tests/event_loop
git commit -m "feat: coordinate terminal updates with an event loop"
```

### Task 5: Make terminal composition dirty-aware

**Files:**
- Modify: `src/tuiloom/render/terminal_renderer.py`
- Modify: `tests/render/test_terminal_renderer.py`

- [ ] **Step 1: Write a failing unchanged-composition test**

Add counting subclasses or monkeypatch wrappers around `MenuRenderer.render` and `Viewport.render`:

```python
def test_clean_renderer_skips_complete_frame_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_renderer(monkeypatch, StringIO())
    compose_calls = 0
    original = renderer._compose_frame

    def count(*args: object, **kwargs: object) -> list[str]:
        nonlocal compose_calls
        compose_calls += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(renderer, "_compose_frame", count)
    renderer.render()
    renderer.render()

    assert compose_calls == 1
```

Run: `uv run pytest -q tests/render/test_terminal_renderer.py::test_clean_renderer_skips_complete_frame_composition`

Expected: failure reports two calls instead of one.

- [ ] **Step 2: Track the complete visible render key**

Add a `_last_render_key` containing terminal size, content revision, `menu_renderer.revision`, input buffer, spacing, and viewport offsets. At the start of `render()`, obtain terminal size and the cheap current key. Return immediately when it equals `_last_render_key` and the renderer is not invalidated.

After composition and terminal writing, store the key. `invalidate()` clears both the previous-frame data and `_last_render_key`. Scroll methods rely on viewport offsets entering the next key. `set_content_renderer()` continues to reset viewport and invalidate the complete frame.

Do not remove normalization from `_write_full_frame()` or `_write_segment_changes()`; those methods remain terminal safety boundaries.

- [ ] **Step 3: Run terminal renderer tests and verify GREEN**

Run: `uv run pytest -q tests/render/test_terminal_renderer.py`

Expected: all terminal-renderer tests pass, including ANSI safety tests.

- [ ] **Step 4: Commit dirty-aware terminal composition**

```bash
git add src/tuiloom/render/terminal_renderer.py tests/render/test_terminal_renderer.py
git commit -m "perf: skip clean terminal frame composition"
```

### Task 6: Integrate the event loop with TerminalMenu

**Files:**
- Modify: `src/tuiloom/terminal_menu.py`
- Modify: `tests/test_terminal_menu_input.py`
- Modify: `tests/test_terminal_app.py`

- [ ] **Step 1: Write failing menu lifecycle tests**

Add tests that inject a recording `EventLoop` through a private factory seam:

```python
def test_menu_run_delegates_repeated_work_to_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu = make_menu()
    menu.app.input_handler = FakeInputHandler()
    loop = RecordingEventLoop(menu)
    monkeypatch.setattr(menu, "_create_event_loop", lambda: loop)
    loop.on_run = menu.stop

    menu.run()

    assert loop.run_calls == 1
    assert loop.closed is True


def test_active_content_replacement_is_installed_in_event_loop() -> None:
    menu = make_menu()
    loop = RecordingEventLoop(menu)
    menu.running = True
    menu._event_loop = loop
    stream = iter(["new"])

    menu.set_content_source(stream)

    assert loop.installed_sources == [stream]
```

Add an application-level test whose worker source raises and assert the terminal leave method still runs once. Use fakes rather than a real TTY.

- [ ] **Step 2: Run integration tests and verify RED**

Run: `uv run pytest -q tests/test_terminal_menu_input.py tests/test_terminal_app.py`

Expected: failures report missing `_create_event_loop` and `_event_loop` behavior.

- [ ] **Step 3: Replace the fixed loop**

Remove the `sleep` import and the render/poll/sleep loop. Add `_event_loop: EventLoop | None` initialized to `None`.

After constructing the three renderers, create the event loop and run it:

```python
self._event_loop = self._create_event_loop()

try:
    self._event_loop.run()
finally:
    self._event_loop.close()
    self._event_loop = None
```

`_create_event_loop()` validates the initialized renderer and input-handler state, then returns an `EventLoop` with explicit keyword arguments.

Change `set_content_source()` so an active menu delegates replacement to `self._event_loop.install_source(content_source)`. The event loop creates the replacement `ContentRenderer`, passes it to `TerminalRenderer.set_content_renderer()`, and starts the source worker when required.

Keep `_handle_event()` and its focused handlers on `TerminalMenu`. The event loop calls them and requests rendering after input changes. Preserve the user's existing empty-command behavior and every existing message/public-API edit in the dirty worktree.

- [ ] **Step 4: Run integration tests and verify GREEN**

Run: `uv run pytest -q tests/test_terminal_menu_input.py tests/test_terminal_app.py`

Expected: all integration tests pass.

- [ ] **Step 5: Run the full suite after lifecycle integration**

Run: `uv run pytest -q`

Expected: all existing and new tests pass.

- [ ] **Step 6: Commit event-loop integration without staging user changes**

Use `git diff` and interactive or patch staging to isolate only implementation hunks in files that already contained user edits.

```bash
git add tests/test_terminal_menu_input.py tests/test_terminal_app.py
git add -p src/tuiloom/terminal_menu.py
git commit -m "feat: run terminal menus from event notifications"
```

### Task 7: Add performance regression coverage and documentation

**Files:**
- Create: `benchmarks/rendering.py`
- Modify: `README.md`

- [ ] **Step 1: Create the reproducible benchmark**

Create `benchmarks/rendering.py` with two timed cases using `perf_counter()`:

1. 500 clean render attempts over 8 KiB of static content after one initial frame;
2. 4,000 one-character chunks delivered in batches of 64 to `ContentRenderer`.

Print case name, total elapsed time, milliseconds per attempted frame or chunk, and the number of real `_compose_frame()` calls. Use `StringIO` for terminal output and a fixed `os.terminal_size((100, 30))`. Do not assert wall-clock thresholds in this script.

- [ ] **Step 2: Run benchmark and verify structural results**

Run: `uv run python benchmarks/rendering.py`

Expected:

- the clean-render case reports one real composition after its initial frame;
- the streaming case reports 63 batch updates for 4,000 chunks;
- total time is substantially below the recorded pre-refactor baselines of 5.5 seconds for 500 unchanged frames and 18.5 seconds for 4,000 one-character stream updates on the development machine.

- [ ] **Step 3: Document streaming behavior**

Add a `## Streaming performance` section to `README.md` explaining that synchronous iterators keep the public API shown in the existing example, run outside the UI thread, publish through a bounded buffer, and render in batches at up to 60 FPS. State that generators should still release the GIL during long native work when possible and must eventually return from blocked `next()` calls for prompt resource cleanup.

- [ ] **Step 4: Commit benchmark and documentation**

```bash
git add benchmarks/rendering.py README.md
git commit -m "docs: describe event-driven streaming performance"
```

### Task 8: Final verification and Call-Me-Maybe smoke test

**Files:**
- Verify only: all files changed in Tasks 1–7

- [ ] **Step 1: Run formatting and lint checks**

Run: `uv run ruff format --check . && uv run ruff check .`

Expected: both commands exit successfully with no diagnostics.

- [ ] **Step 2: Run strict type checking**

Run: `uv run mypy`

Expected: mypy exits successfully with no errors.

- [ ] **Step 3: Run the complete test suite**

Run: `uv run pytest -q`

Expected: every existing and new test passes.

- [ ] **Step 4: Run the benchmark one final time**

Run: `uv run python benchmarks/rendering.py`

Expected: one clean-frame composition, 63 streaming batches, and no regression toward the recorded quadratic baselines.

- [ ] **Step 5: Smoke-test the editable consumer without modifying it**

From `/home/maroard/Bureau/42/Cercle-3/Call-Me-Maybe`, run its terminal application with the existing editable Tuiloom dependency. Start generation, type while generation is active, scroll, and exit after completion.

Expected: generation continues, input and cursor remain responsive, scrolling does not freeze, and Call-Me-Maybe requires no source-code change. If model assets or a usable TTY are unavailable, record that environmental limitation and rely on the deterministic Tuiloom integration tests instead.

- [ ] **Step 6: Inspect the final diff and working tree**

Run: `git status --short && git diff --check && git log --oneline -10`

Expected: no whitespace errors; user-owned pre-existing modifications remain present and uncommitted unless the user separately asked to include them; implementation commits are visible in task order.
