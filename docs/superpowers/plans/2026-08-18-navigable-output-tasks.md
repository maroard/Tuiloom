# Navigable Background Output Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep captured-output work alive while users navigate between menus, show its progress only in the originating menu, and remove that progress when the task completes.

**Architecture:** Move task execution and completion ownership from a menu's temporary `EventLoop` into `TerminalApp`. A thread-safe task session stores replayable output, while each run of the originating menu creates a fresh iterator view over that session; every active event loop dispatches application-owned outcomes on the UI thread.

**Tech Stack:** Python 3.12, threading, queues/conditions, pytest, mypy, Ruff, Flake8.

**Repository note:** Both worktrees intentionally contain uncommitted user changes. Do not create commits; edit and verify only the files listed below.

---

## File structure

### Tuiloom

- Modify `src/tuiloom/output_task.py`: define the application-owned task session and replayable output iterator.
- Modify `src/tuiloom/terminal_app.py`: start one captured-output task, receive outcomes, and dispatch completion on the UI thread.
- Modify `src/tuiloom/terminal_menu.py`: attach/detach a task view without replacing the menu's ordinary content and keep navigation enabled.
- Modify `src/tuiloom/event_loop/event_loop.py`: poll application task outcomes from whichever menu is active.
- Modify `src/tuiloom/event_loop/source_worker.py`: return to consuming only iterator and dynamic content sources.
- Modify `src/tuiloom/event_loop/source_event.py`: remove task-specific source events.
- Modify `src/tuiloom/render/content_renderer.py`: remove `OutputTask` as a content-source variant.
- Modify tests under `tests/`: specify session replay, navigation, origin-only display, UI-thread outcome dispatch, cleanup, and concurrency behavior.
- Modify `README.md`: document navigable output-task semantics.

### Call-Me-Maybe

- Modify `src/terminal_app/menus/main/options/model/model_menu.py`: rely on persistent `run_with_output` and clear progress on either outcome.
- Modify `tests/terminal_app/menus/main/options/model/test_model_menu.py`: specify the final success/error presentation.

---

### Task 1: Build a replayable application-owned task session

**Files:**
- Modify: `src/tuiloom/output_task.py`
- Modify: `tests/test_output_capture.py`
- Create: `tests/test_output_task.py`

- [ ] **Step 1: Write failing session tests**

Add tests equivalent to:

```python
def test_session_replays_output_to_a_view_created_after_writes() -> None:
    session = make_session(lambda: None)
    session.append_output("10%\r")
    session.append_output("20%\n")
    session.finish_success(None)

    assert list(session.iter_output()) == ["10%\r", "20%\n"]


def test_session_view_waits_for_new_output_until_completion() -> None:
    session = make_session(lambda: None)
    view = session.iter_output()
    received: list[str] = []
    reader = Thread(target=lambda: received.extend(view))
    reader.start()
    session.append_output("downloading")
    session.finish_success(42)
    reader.join(timeout=1)

    assert received == ["downloading"]
    assert session.outcome.result == 42
```

Also cover failure storage and a cancelled view stopping without cancelling the session.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
uv run pytest tests/test_output_task.py -v
```

Expected: failures because `OutputTaskSession`, replay, and stored outcomes do not exist.

- [ ] **Step 3: Implement the minimal session**

Replace the callable-only `OutputTask` transport with an internal session that owns:

```python
@dataclass(frozen=True)
class OutputTaskOutcome:
    result: object = None
    error: Exception | None = None


class OutputTaskSession:
    def append_output(self, text: str) -> None: ...
    def iter_output(self) -> Iterator[str]: ...
    def finish_success(self, result: object) -> None: ...
    def finish_error(self, error: Exception) -> None: ...
```

Use a `Condition`, an append-only `list[str]`, a completion flag, and one cursor per iterator. A newly created iterator starts at index zero, which supplies replay after reopening the menu. Closing an iterator only stops that view.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run pytest tests/test_output_task.py tests/test_output_capture.py -v
uv run mypy src/tuiloom/output_task.py
uv run ruff check src/tuiloom/output_task.py tests/test_output_task.py
```

Expected: all pass.

### Task 2: Move execution and completion dispatch into TerminalApp

**Files:**
- Modify: `src/tuiloom/terminal_app.py`
- Modify: `tests/test_terminal_app.py`

- [ ] **Step 1: Write failing application lifecycle tests**

Add tests showing that the application owns the thread and that callbacks are delayed until UI dispatch:

```python
def test_application_runs_output_action_but_dispatches_callback_later() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)
    callbacks: list[object] = []

    with app._output_capture.install():
        session = app._start_output_task(
            menu,
            lambda: print("download") or 42,
            callbacks.append,
            pytest.fail,
        )
        session.join(timeout=1)

        assert callbacks == []
        assert list(session.iter_output()) == ["download", "\n"]
        app._dispatch_output_task_outcome()

    assert callbacks == [42]
```

Add tests that:

- starting a second captured-output task raises `RuntimeError`;
- dispatch detaches the task before its callback;
- both success and failure release the application task slot.

- [ ] **Step 2: Run the lifecycle tests and verify RED**

Run:

```bash
uv run pytest tests/test_terminal_app.py -k output_task -v
```

Expected: failures because `TerminalApp` does not own task sessions.

- [ ] **Step 3: Implement application ownership**

Add private state similar to:

```python
self._active_output_task: OutputTaskSession | None = None
self._output_task_outcomes: Queue[OutputTaskSession] = Queue()
```

`_start_output_task()` must:

1. reject an existing unfinished session;
2. create a session containing the origin menu and callbacks;
3. start a daemon worker;
4. route background stdout/stderr into `session.append_output`;
5. store success or failure and enqueue the session.

`_dispatch_output_task_outcome()` must run on the caller's UI thread, detach the originating menu, clear the active application slot, and then invoke exactly one completion callback.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run pytest tests/test_terminal_app.py -k output_task -v
uv run mypy src/tuiloom/terminal_app.py src/tuiloom/output_task.py
uv run ruff check src/tuiloom/terminal_app.py tests/test_terminal_app.py
```

Expected: all pass.

### Task 3: Attach task output to its originating menu without blocking navigation

**Files:**
- Modify: `src/tuiloom/terminal_menu.py`
- Modify: `tests/test_terminal_menu_input.py`

- [ ] **Step 1: Write failing menu behavior tests**

Replace the old command-blocking expectation with:

```python
def test_output_task_keeps_commands_and_navigation_available() -> None:
    menu = running_menu()
    calls: list[str] = []
    menu.add_command("Action", lambda context: calls.append("action"), index=1)
    menu.run_with_output(blocking_action, on_success=noop, on_error=noop)

    enter(menu, "1")
    menu._handle_event(InputEvent("escape", None))

    assert calls == ["action"]
    assert menu.running is False
```

Add tests that the ordinary `_content_source` is preserved, reopening uses a fresh replay iterator for the same session, another menu keeps its own content, and detach reinstalls ordinary content only when the origin menu is active.

- [ ] **Step 2: Run these tests and verify RED**

Run:

```bash
uv run pytest tests/test_terminal_menu_input.py -k output_task -v
```

Expected: failures because current task input is suppressed and its worker dies with the menu event loop.

- [ ] **Step 3: Implement menu attachment**

Keep separate state:

```python
self._output_task_session: OutputTaskSession | None = None
self._output_task_previous_auto_scroll: AutoScrollMode | None = None
```

`run_with_output()` delegates to `app._start_output_task()` and installs only `session.iter_output()` into the live renderer. It must not replace `_content_source`.

`run()` selects `session.iter_output()` when a task is attached, otherwise it selects the ordinary content source. Remove `_output_task_running` input suppression so `_handle_event()` always dispatches normal commands, Back/Escape, and scrolling.

`_detach_output_task()` restores auto-scroll, removes the association, and reinstalls the ordinary content only if the menu currently owns a live event loop.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run pytest tests/test_terminal_menu_input.py -k "output_task or run_with_output" -v
uv run mypy src/tuiloom/terminal_menu.py
uv run ruff check src/tuiloom/terminal_menu.py tests/test_terminal_menu_input.py
```

Expected: all pass.

### Task 4: Dispatch outcomes from whichever menu event loop is active

**Files:**
- Modify: `src/tuiloom/event_loop/event_loop.py`
- Modify: `tests/event_loop/test_event_loop.py`

- [ ] **Step 1: Write failing cross-menu dispatch tests**

Add a test whose active event loop belongs to a different menu from the task origin:

```python
def test_active_child_loop_dispatches_another_menus_task_outcome() -> None:
    origin = make_menu(app, "Model")
    active = make_menu(app, "Configuration")
    session = completed_session(origin, result=42)
    app._active_output_task = session
    app._output_task_outcomes.put(session)

    loop = make_event_loop(active)
    loop.run_once()

    assert received == [42]
    assert origin._output_task_session is None
```

Also verify that output never becomes the active menu's content source.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
uv run pytest tests/event_loop/test_event_loop.py -k output_task -v
```

Expected: failure because event loops do not dispatch application outcomes.

- [ ] **Step 3: Poll application outcomes in `run_once()`**

Call `self.menu.app._dispatch_output_task_outcome()` during every loop turn after input/source draining and before rendering. Request an immediate render when dispatch changed the currently active menu.

No application output is installed into the active menu unless that menu is the task's recorded origin.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run pytest tests/event_loop/test_event_loop.py -v
uv run mypy src/tuiloom/event_loop/event_loop.py
uv run ruff check src/tuiloom/event_loop/event_loop.py tests/event_loop/test_event_loop.py
```

Expected: all pass.

### Task 5: Remove the obsolete source-worker task transport

**Files:**
- Modify: `src/tuiloom/event_loop/source_worker.py`
- Modify: `src/tuiloom/event_loop/source_event.py`
- Modify: `src/tuiloom/render/content_renderer.py`
- Modify: `tests/event_loop/test_source_worker.py`
- Modify: `tests/render/test_content_renderer.py`
- Modify: `tests/test_public_api.py`

- [ ] **Step 1: Update tests to reject OutputTask as a content source**

Delete task outcome tests from `SourceWorker` and assert that supported `ContentSource` values remain static text, line lists, iterators, and refresh callables. Preserve all carriage-return streaming tests.

- [ ] **Step 2: Run the focused tests before cleanup**

Run:

```bash
uv run pytest tests/event_loop/test_source_worker.py tests/render/test_content_renderer.py tests/test_public_api.py -v
```

Expected: failures or collection errors until obsolete task-source branches are removed consistently.

- [ ] **Step 3: Remove obsolete branches**

Remove `task_success`, `task_error`, and `result` from `SourceEvent`; remove `OutputTask` handling from `SourceWorker`, `ContentSource`, `ContentRenderer`, and `EventLoop._handle_source_event()`.

Keep iterator streaming intact because task views now reuse that established path.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run pytest tests/event_loop/test_source_worker.py tests/render/test_content_renderer.py tests/test_public_api.py -v
uv run mypy src
uv run ruff check src tests
```

Expected: all pass.

### Task 6: Clear ModelMenu progress and preserve transactional updates

**Files:**
- Modify: `/home/maroard/Bureau/42/Cercle-3/Call-Me-Maybe/tests/terminal_app/menus/main/options/model/test_model_menu.py`
- Modify: `/home/maroard/Bureau/42/Cercle-3/Call-Me-Maybe/src/terminal_app/menus/main/options/model/model_menu.py`

- [ ] **Step 1: Write failing presentation tests**

Update the task recorder to model attachment/detachment and add assertions:

```python
def test_success_removes_download_output_and_leaves_only_updated_message() -> None:
    menu, task = start_model_download("google/gemma-3-270m")
    task.append_output("Downloading 100%")

    task.complete_success(candidate_model)

    assert menu._output_task_session is None
    assert menu._content_source is None
    assert menu.screen_context.message == "Model updated."
    assert menu.screen_context.text == "Model: google/gemma-3-270m"


def test_failure_removes_download_output_and_restores_model_input() -> None:
    menu, task = start_model_download("owner/missing")
    task.complete_error(OSError("network"))

    assert menu._output_task_session is None
    assert menu._content_source is None
    assert menu._input_behavior == menu._submit_model_name
```

- [ ] **Step 2: Run the ModelMenu tests and verify RED**

Run from Call-Me-Maybe:

```bash
uv run pytest tests/terminal_app/menus/main/options/model/test_model_menu.py -v
```

Expected: the final content assertions fail with the old persistent-output behavior.

- [ ] **Step 3: Adapt ModelMenu callbacks**

Keep `_submit_model_name()` responsible for starting the task. Let Tuiloom detach progress before `_apply_model()` or `_handle_model_error()` runs. `_apply_model()` updates the candidate and leaves exactly:

```python
self.screen_context.text = f"Model: {candidate.model_name}"
self.screen_context.message = "Model updated."
```

The failure callback preserves the old model, re-enters model-name input, and sets only the concise formatted error.

- [ ] **Step 4: Verify GREEN**

Run from Call-Me-Maybe:

```bash
uv run pytest tests/terminal_app/menus/main/options/model/test_model_menu.py -v
uv run mypy --follow-imports=skip src/terminal_app/menus/main/options/model/model_menu.py
uv run flake8 src/terminal_app/menus/main/options/model/model_menu.py tests/terminal_app/menus/main/options/model/test_model_menu.py
```

Expected: all pass.

### Task 7: Documentation and final verification

**Files:**
- Modify: `README.md`
- Verify both repositories.

- [ ] **Step 1: Document final semantics**

Update the `run_with_output()` example to state that the application owns the task, navigation remains enabled, output is replayed only in the origin menu, and completion removes the transient content before invoking callbacks.

- [ ] **Step 2: Run the complete Tuiloom verification**

Run:

```bash
uv run pytest
uv run mypy src
uv run ruff check src tests
git diff --check
```

Expected: all pass.

- [ ] **Step 3: Run scoped Call-Me-Maybe verification**

Run:

```bash
uv run pytest tests/terminal_app/menus/main/options/model/test_model_menu.py
uv run mypy --follow-imports=skip src/terminal_app/menus/main/options/model/model_menu.py
uv run flake8 src/terminal_app/menus/main/options/model/model_menu.py tests/terminal_app/menus/main/options/model/test_model_menu.py
git diff --check
```

Expected: all pass. Do not run the complete Call-Me-Maybe suite unless the user changes the earlier instruction.

- [ ] **Step 4: Perform a manual lifecycle scenario**

Use a controlled blocking action to verify this sequence:

1. start output in `ModelMenu`;
2. leave for `ConfigurationMenu` while output continues;
3. return to `ModelMenu` and observe replay plus live progress;
4. leave again and let the task complete;
5. return and observe no progress content and only the final message.

Expected: no duplicate action execution, no output leakage into other menus, and no terminal corruption.
