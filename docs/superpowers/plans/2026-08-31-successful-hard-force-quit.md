# Successful Hard Force Quit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Treat a user-selected hard Force quit as a successful process exit so Make and other launchers do not report a false failure.

**Architecture:** Keep the existing terminal-restoration and hard-process-termination path unchanged. Change only its exit status from 1 to 0, and lock that contract with both lifecycle-order and real PTY subprocess tests.

**Tech Stack:** Python 3.12+, pytest, POSIX PTY/subprocess integration tests

---

### Task 1: Return success after a handled Force quit

**Files:**
- Modify: `tests/test_terminal_app.py:72-115`
- Modify: `tests/test_pty.py:152-193`
- Modify: `src/tuiloom/terminal_app.py:294-318`
- Modify: `README.md:398-407`

- [ ] **Step 1: Change the tests to require status zero**

In `test_hard_exit_restores_terminal_before_terminating_process`, change the
final expected call:

```python
assert calls == [
    "enter",
    ("shutdown", False),
    "input closed",
    "leave",
    ("exit", 0),
]
```

In `test_force_quit_restores_terminal_and_kills_blocked_output_task`, require:

```python
assert process.returncode == 0
```

- [ ] **Step 2: Run both tests and verify RED**

Run:

```bash
uv run pytest tests/test_terminal_app.py::test_hard_exit_restores_terminal_before_terminating_process tests/test_pty.py::test_force_quit_restores_terminal_and_kills_blocked_output_task -v
```

Expected: both tests FAIL because production still calls `_exit(1)`.

- [ ] **Step 3: Make the minimal production change**

Change the final hard-exit call in `TerminalApp.run()`:

```python
if hard_exit_requested:
    _exit(0)
```

- [ ] **Step 4: Align the public documentation**

Replace the Force quit status wording in `README.md` with:

```markdown
- **Force quit** immediately restores the terminal and terminates the process
  with status zero because it is an explicitly handled user action. It does not
  wait for active Python threads or native calls, and it does not run their
  completion callbacks. Partial third-party writes, such as model cache
  downloads, may be resumed or cleaned up by that library on the next launch.
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_terminal_app.py::test_hard_exit_restores_terminal_before_terminating_process tests/test_pty.py::test_force_quit_restores_terminal_and_kills_blocked_output_task -v
```

Expected: both tests PASS; the PTY child returns zero after restoring the
alternate screen despite its blocked worker.

- [ ] **Step 6: Run the complete quality gate**

Run:

```bash
make check
git diff --check
```

Expected: Ruff, format, mypy, all tests, and the 90% coverage threshold PASS;
the diff has no whitespace errors.

- [ ] **Step 7: Commit and update the open branch**

```bash
git add src/tuiloom/terminal_app.py tests/test_terminal_app.py tests/test_pty.py README.md
git commit -m "fix: treat force quit as successful exit"
git push
```

