# Hard Force Quit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make **Force quit** restore the terminal and terminate the process immediately, even when active Python or native work never returns.

**Architecture:** The root menu records an irreversible hard-exit request and stops its event loop immediately. Normal cleanup retains cooperative cancellation and joins, while a distinct abandon path only releases Tuiloom-owned selector resources; the application then calls an internal `os._exit` boundary after restoring terminal modes.

**Tech Stack:** Python 3.12+, Tuiloom, pytest, POSIX PTY/subprocess integration tests

---

## File map

- `src/tuiloom/terminal_menu.py`: record the hard-exit request, stop rendering, and select non-waiting event-loop cleanup.
- `src/tuiloom/event_loop/event_loop.py`: support closing Tuiloom-owned resources without calling application workers.
- `src/tuiloom/terminal_app.py`: skip output-worker joins, restore terminal state, and invoke the hard process terminator.
- `src/tuiloom/task_exit.py`: remove the obsolete `stopping` state and its rendered message.
- `tests/test_task_exit.py`: specify immediate, irreversible menu behavior.
- `tests/event_loop/test_event_loop.py`: specify that hard cleanup neither cancels nor joins blocked work.
- `tests/test_terminal_app.py`: specify cleanup and process-termination ordering.
- `tests/test_pty.py`: prove from a real child process that blocked work cannot delay exit and that the alternate screen is restored.
- `README.md`: document the new destructive Force quit contract and preserve the distinction from Wait and quit.

### Task 1: Make the menu request an immediate hard exit

**Files:**
- Modify: `tests/test_task_exit.py:309-357`
- Modify: `src/tuiloom/terminal_menu.py:57-90,498-535,838-878`
- Modify: `src/tuiloom/task_exit.py:6-39`

- [ ] **Step 1: Replace the old stopping-state test with a failing immediate-exit test**

Replace `test_source_work_offers_exit_choices_and_stop_waits_for_real_termination` with:

```python
def test_force_quit_requests_hard_exit_without_waiting_for_work() -> None:
    _, menu = make_main()
    _, (work,) = install_fake_operations(menu, "Generating function calls")

    menu.stop()
    press(menu, "enter")

    assert menu._hard_exit_requested
    assert not menu._running
    assert menu._task_exit is None
    assert work.alive
    assert not work.cancelled
```

Delete `test_force_quit_cancels_operations_that_appear_while_stopping`; there is
no interactive stopping interval in which new operations can appear.
Also delete `test_stop_and_quit_waits_and_discards_future_output_and_callbacks`;
Task 3 replaces it with coverage of the new non-waiting output-task shutdown.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
uv run pytest tests/test_task_exit.py::test_force_quit_requests_hard_exit_without_waiting_for_work -v
```

Expected: FAIL because `TerminalMenu` has no `_hard_exit_requested` attribute
and still remains in `stopping` mode.

- [ ] **Step 3: Implement the minimal menu state transition**

Initialize the flag in `TerminalMenu.__init__` alongside `_running`:

```python
self._running = False
self._hard_exit_requested = False
```

Change the Force quit branch in `_activate_task_exit_row`:

```python
if row == "Force quit":
    self._hard_exit_requested = True
    self._task_exit = None
    self._stop_immediately()
```

Narrow `TaskExitMode` and remove dead stopping rendering from `task_exit.py`:

```python
type TaskExitMode = Literal["choice", "waiting"]
```

```python
def visible_title(self, operation_count: int) -> str:
    """Return the count-sensitive temporary menu title."""
    plural = operation_count != 1
    return "Operations in progress" if plural else "Operation in progress"
```

Remove the now-unreachable `view.mode == "stopping"` checks from
`_handle_task_exit_event` and `_tick_task_exit`. Delete
`_cancel_panel_operation`, which was used only by those branches.

- [ ] **Step 4: Run the task-exit tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_task_exit.py -v
```

Expected: all tests PASS after updating any assertion that referenced the
removed `stopping` mode; Wait and quit and Cancel tests remain unchanged.

- [ ] **Step 5: Commit the menu behavior**

```bash
git add src/tuiloom/terminal_menu.py src/tuiloom/task_exit.py tests/test_task_exit.py
git commit -m "fix: make force quit leave the menu immediately"
```

### Task 2: Add a non-waiting event-loop cleanup path

**Files:**
- Modify: `tests/event_loop/test_event_loop.py:361-386`
- Modify: `src/tuiloom/event_loop/event_loop.py:200-219`
- Modify: `src/tuiloom/terminal_menu.py:524-533`

- [ ] **Step 1: Write a failing test proving hard cleanup does not touch workers**

Add a worker double and focused test:

```python
class UnstoppableWork:
    def __init__(self) -> None:
        self.cancel_calls = 0
        self.join_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1

    def join(self, timeout: float | None = None) -> bool:
        self.join_calls += 1
        return False

    def is_alive(self) -> bool:
        return True


def test_abandon_releases_resources_without_touching_workers() -> None:
    menu, loop, selector, _ = make_loop([None])
    work = UnstoppableWork()
    panel = menu.content_panels[0]
    panel._worker = cast(SourceWorker, work)

    loop.abandon()

    assert work.cancel_calls == 0
    assert work.join_calls == 0
    assert selector.closed
    assert loop._wakeup_reader.fileno() == -1
    assert loop._wakeup_writer.fileno() == -1
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
uv run pytest tests/event_loop/test_event_loop.py::test_abandon_releases_resources_without_touching_workers -v
```

Expected: FAIL with `AttributeError` because `EventLoop` has no `abandon()`
method.

- [ ] **Step 3: Implement the explicit cleanup policy**

Keep normal `close()` semantics and extract resource closure so a separate hard
path cannot accidentally call application code:

```python
def close(self) -> None:
    """Cancel and join source work before releasing selectable resources."""
    if self._closed:
        return

    self._closed = True
    self._pending_source = None
    panels = tuple(
        dict.fromkeys((*self._menu.content_panels, *self._retiring_panels))
    )
    for panel in panels:
        if panel._worker is not None:
            panel._worker.cancel()
    for panel in panels:
        if panel._worker is not None:
            panel._worker.join()
    self._close_resources()

def abandon(self) -> None:
    """Release selectable resources without touching application workers."""
    if self._closed:
        return
    self._closed = True
    self._pending_source = None
    self._close_resources()

def _close_resources(self) -> None:
    """Close the selector and wakeup sockets exactly once."""
    self._selector.close()
    self._wakeup_reader.close()
    self._wakeup_writer.close()
```

The hard path deliberately avoids `cancel()`: iterator cancellation is
application code and can itself block. `_notify_source()` already tolerates a
closed wakeup socket if a worker races with process termination.

Wire the menu to the new path before clearing its loop reference:

```python
try:
    self._event_loop.run()
finally:
    if self._hard_exit_requested:
        self._event_loop.abandon()
    else:
        self._event_loop.close()
    self._event_loop = None
```

- [ ] **Step 4: Run event-loop tests and verify GREEN**

Run:

```bash
uv run pytest tests/event_loop/test_event_loop.py -v
```

Expected: all tests PASS, including the existing proof that normal `close()`
still waits for cooperative cancellation.

- [ ] **Step 5: Commit event-loop cleanup**

```bash
git add src/tuiloom/event_loop/event_loop.py src/tuiloom/terminal_menu.py tests/event_loop/test_event_loop.py
git commit -m "feat: add non-waiting event loop cleanup"
```

### Task 3: Restore the terminal and terminate the process

**Files:**
- Modify: `tests/test_terminal_app.py:35-145`
- Modify: `tests/test_pty.py:1-75, final section`
- Modify: `src/tuiloom/terminal_app.py:1-10,281-322`

- [ ] **Step 1: Write a failing unit test for cleanup ordering**

Add this test to `tests/test_terminal_app.py`:

```python
def test_hard_exit_restores_terminal_before_terminating_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HardExitObserved(BaseException):
        pass

    class FakeInputHandler:
        def close(self) -> None:
            calls.append("input closed")

    app = TerminalApp("App")
    menu = TerminalMenu(app, ScreenContext("main", "Main"))
    app.set_main_menu(menu)
    calls: list[object] = []

    def run_menu() -> None:
        menu._hard_exit_requested = True

    def terminate(status: int) -> None:
        calls.append(("exit", status))
        raise HardExitObserved

    monkeypatch.setattr("tuiloom.terminal_app.InputHandler", FakeInputHandler)
    monkeypatch.setattr(app, "_enter_terminal_screen", lambda: calls.append("enter"))
    monkeypatch.setattr(app, "_leave_terminal_screen", lambda: calls.append("leave"))
    monkeypatch.setattr(
        app,
        "_shutdown_output_task",
        lambda *, wait_for_worker=True: calls.append(
            ("shutdown", wait_for_worker)
        ),
    )
    monkeypatch.setattr(menu, "run", run_menu)
    monkeypatch.setattr("tuiloom.terminal_app._exit", terminate)

    with pytest.raises(HardExitObserved):
        app.run()

    assert calls == [
        "enter",
        ("shutdown", False),
        "input closed",
        "leave",
        ("exit", 1),
    ]
```

- [ ] **Step 2: Add coverage for bounded output-task abandonment**

Add this direct test to `tests/test_task_exit.py`:

```python
def test_hard_output_shutdown_does_not_wait_and_discards_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_stdout = io.StringIO()
    original_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", original_stdout)
    monkeypatch.setattr(sys, "stderr", original_stderr)
    app, menu = make_main()
    started = Event()
    release = Event()
    callbacks: list[str] = []

    def action() -> None:
        started.set()
        release.wait(1)
        print("late")

    with app._output_capture.install():
        session = app._start_output_task(
            menu,
            action,
            lambda result: callbacks.append("success"),
            lambda error: callbacks.append("error"),
            "Work",
        )
        attach_output_task(app, menu, session, "Work")
        assert started.wait(1)

        app._shutdown_output_task(wait_for_worker=False)

        assert session.is_alive()
        assert app._active_output_task is None
        release.set()
        assert session.join(1)
        assert app._dispatch_output_task_outcome() is None

    assert "late" not in original_stdout.getvalue()
    assert callbacks == []
```

- [ ] **Step 3: Write a failing PTY regression test for an immortal worker**

Add a bounded child-process reader:

```python
def _read_to_exit(
    master: int,
    process: subprocess.Popen[bytes],
    *,
    timeout: float = 2,
) -> bytes:
    output = bytearray()
    deadline = monotonic() + timeout
    while monotonic() < deadline and process.poll() is None:
        readable, _, _ = select.select([master], [], [], 0.1)
        if readable:
            try:
                output.extend(os.read(master, 8192))
            except OSError:
                break
    process.wait(timeout=max(0.1, deadline - monotonic()))
    while True:
        readable, _, _ = select.select([master], [], [], 0)
        if not readable:
            return bytes(output)
        try:
            output.extend(os.read(master, 8192))
        except OSError:
            return bytes(output)
```

Then add:

```python
def test_force_quit_restores_terminal_and_kills_blocked_output_task() -> None:
    script = """
from threading import Event
from tuiloom import ScreenContext, TerminalApp, TerminalMenu

app = TerminalApp("App")
menu = TerminalMenu(app, ScreenContext("main", "Main"))
def block_forever():
    print("TASK_STARTED")
    Event().wait()
menu.add_command(
    "Start",
    lambda context: menu.run_with_output(
        block_forever,
        on_success=lambda result: None,
        on_error=lambda error: None,
        description="Blocked",
    ),
)
app.set_main_menu(menu)
app.run()
"""
    process, master = _spawn(script)
    try:
        _read_until(master, process, b"Start")
        os.write(master, b"\r")
        _read_until(master, process, b"TASK_STARTED")
        os.write(master, b"\x1b")
        choice = _read_until(master, process, b"Force quit")
        os.write(master, b"\r")
        final = choice + _read_to_exit(master, process)

        assert process.returncode == 1
        assert b"\x1b[?1049l" in final
        assert b"Stopping operation" not in final
    finally:
        os.close(master)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
```

- [ ] **Step 4: Run all three tests and verify RED**

Run:

```bash
uv run pytest tests/test_terminal_app.py::test_hard_exit_restores_terminal_before_terminating_process tests/test_task_exit.py::test_hard_output_shutdown_does_not_wait_and_discards_callbacks tests/test_pty.py::test_force_quit_restores_terminal_and_kills_blocked_output_task -v
```

Expected: the unit test FAILS because no terminator is called; the task test
FAILS because `_shutdown_output_task` has no policy argument; the PTY test times
out or reports that the child remains alive behind its blocked worker. The test
cleanup kills that child, so the suite itself cannot hang.

- [ ] **Step 5: Implement bounded output-task cleanup and hard termination**

Import the process boundary:

```python
from os import _exit
```

Change output-task shutdown to cancel internal output delivery but skip the
worker join on a hard exit:

```python
def _shutdown_output_task(self, *, wait_for_worker: bool = True) -> None:
    """Abandon an active task, optionally waiting for its worker."""
    registration = self._active_output_task
    if registration is None:
        return
    registration.on_success = None
    registration.on_error = None
    self._active_output_task = None
    registration.session.cancel()
    registration.menu._abandon_output_task(registration.session)
    if wait_for_worker:
        registration.session.join()
```

Delete `_stop_and_quit_output_task`; the removed stopping-menu path was its only
caller, and hard cleanup is now centralized in `_shutdown_output_task`.

Restructure `TerminalApp.run()` finalization so hard exit wins even if bounded
cleanup or terminal restoration raises:

```python
with self._output_capture.install():
    self._input_handler = InputHandler()
    try:
        self._enter_terminal_screen()
        main_menu.run()
    finally:
        hard_exit_requested = main_menu._hard_exit_requested
        try:
            self._shutdown_output_task(
                wait_for_worker=not hard_exit_requested,
            )
        finally:
            try:
                self._input_handler.close()
            finally:
                self._input_handler = None
                try:
                    self._leave_terminal_screen()
                finally:
                    if hard_exit_requested:
                        _exit(1)
```

Calling `_exit` inside the capture context is intentional: the terminal has
already been restored, while the still-alive worker cannot regain normal
stdout/stderr in the interval before process death.

- [ ] **Step 6: Run focused and lifecycle tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_terminal_app.py tests/test_task_exit.py tests/event_loop/test_event_loop.py tests/test_pty.py -v
```

Expected: all tests PASS; the PTY child exits with status 1 within two seconds
and emits the alternate-screen leave sequence.

- [ ] **Step 7: Commit process termination**

```bash
git add src/tuiloom/terminal_app.py tests/test_terminal_app.py tests/test_task_exit.py tests/test_pty.py
git commit -m "fix: terminate blocked work on force quit"
```

### Task 4: Update the public contract and run the complete quality gate

**Files:**
- Modify: `README.md:386-423,1044-1068`

- [ ] **Step 1: Update Safe shutdown documentation**

Replace the Force quit description with:

```markdown
- **Force quit** immediately restores the terminal and terminates the process
  with a non-zero status. It does not wait for active Python threads or native
  calls, and it does not run their completion callbacks. Partial third-party
  writes, such as model cache downloads, may be resumed or cleaned up by that
  library on the next launch.
```

Keep the Wait and quit description, and replace the paragraph claiming that all
shutdown is cooperative with:

```markdown
**Wait and quit** and ordinary shutdown use cooperative cancellation and wait
without a timeout before restoring the terminal. **Force quit** is the escape
hatch for native or application code that does not return: it restores terminal
modes and then terminates the whole process without waiting for workers.
```

Update Runtime constraints:

```markdown
- Normal shutdown joins non-daemon content and task workers before returning.
  Force quit instead restores terminal modes and terminates the process without
  joining workers.
```

- [ ] **Step 2: Run formatting and static checks**

Run:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
```

Expected: all commands exit 0 with no diagnostics.

- [ ] **Step 3: Run the complete test suite with coverage**

Run:

```bash
uv run pytest --cov=tuiloom --cov-report=term-missing
```

Expected: all tests PASS and total branch coverage remains at or above 90%.

- [ ] **Step 4: Check the final diff**

Run:

```bash
git diff --check HEAD~3..HEAD
git status --short
```

Expected: no whitespace errors; only the pre-existing untracked `.superpowers/`
entry may remain outside committed work.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md
git commit -m "docs: document hard force quit semantics"
```
