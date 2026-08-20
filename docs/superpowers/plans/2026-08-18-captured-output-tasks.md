# Captured Output Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run blocking operations outside Tuiloom's UI thread while streaming their stdout and stderr into the current menu.

**Architecture:** Add an internal captured-task source consumed by `SourceWorker`, route non-UI standard-stream writes into source events while an application runs, and dispatch typed completion callbacks from `EventLoop`. Extend streaming normalization for carriage-return progress updates, then use the API for Call-Me-Maybe model loading.

**Tech Stack:** Python 3.12, threads, queues, Tuiloom event loop, pytest, mypy, Ruff.

---

### Task 1: Render carriage-return progress updates

**Files:**
- Modify: `src/tuiloom/render/content_renderer.py`
- Modify: `tests/render/test_content_renderer.py`

- [ ] Add failing tests for bare `\r` replacement across and within chunks, plus CRLF newline behavior.
- [ ] Add a focused active-line reset path to `_StreamingTextBuffer` and preserve existing ANSI/Unicode chunk handling.
- [ ] Run `uv run pytest tests/render/test_content_renderer.py -v` and require all tests to pass.

### Task 2: Route background standard output safely

**Files:**
- Create: `src/tuiloom/output_capture.py`
- Create: `tests/test_output_capture.py`
- Modify: `src/tuiloom/terminal_app.py`

- [ ] Add failing tests showing UI-thread writes reach the original stream while active background-thread writes reach a capture callback for both stdout and stderr.
- [ ] Test text-stream compatibility (`flush`, `isatty`, `fileno`, `encoding`) and restoration after application exit.
- [ ] Implement application-scoped standard-stream routers with one active background capture and guaranteed restoration.
- [ ] Run `uv run pytest tests/test_output_capture.py tests/test_terminal_app.py -v`.

### Task 3: Execute a captured task through source events

**Files:**
- Create: `src/tuiloom/output_task.py`
- Modify: `src/tuiloom/event_loop/source_event.py`
- Modify: `src/tuiloom/event_loop/source_worker.py`
- Modify: `src/tuiloom/event_loop/event_loop.py`
- Modify: `tests/event_loop/test_source_worker.py`
- Modify: `tests/event_loop/test_event_loop.py`

- [ ] Add failing worker tests for captured stdout/stderr, returned results, handled exceptions, and stream completion.
- [ ] Add failing event-loop tests proving success/error callbacks execute while ordinary source errors still propagate.
- [ ] Implement the internal task source and its success/error event kinds, keeping callback execution in `EventLoop`.
- [ ] Run the two focused event-loop test files.

### Task 4: Expose `TerminalMenu.run_with_output`

**Files:**
- Modify: `src/tuiloom/terminal_menu.py`
- Modify: `tests/test_terminal_menu_input.py`
- Modify: `tests/test_public_api.py`
- Modify: `tests/test_internal_docstrings.py`
- Modify: `README.md`

- [ ] Add failing tests for source replacement, strict following, concurrent-task rejection, callback lifecycle, and input suppression with arrow-key scrolling retained.
- [ ] Implement and document `run_with_output`; keep the task source internal rather than expanding the public symbol list.
- [ ] Add one concise README example.
- [ ] Run the focused menu, public API, and documentation tests.

### Task 5: Integrate Call-Me-Maybe model loading

**Files:**
- Modify: `Call-Me-Maybe/src/terminal_app/menus/main/options/model/model_menu.py`
- Modify: `Call-Me-Maybe/tests/terminal_app/menus/main/options/model/test_model_menu.py`

- [ ] Rewrite the model-submit tests to expect background scheduling and add a captured-output assertion through a lightweight fake operation.
- [ ] Refactor `_submit_model_name` into scheduling, success, and expected-error callbacks while preserving the old model transactionally.
- [ ] Run the focused Call-Me-Maybe model-menu tests.

### Task 6: Verify both repositories

**Files:**
- Verify all files listed above.

- [ ] Run Tuiloom's focused tests, `uv run mypy`, and `uv run ruff check` for touched files.
- [ ] Run Call-Me-Maybe's focused model-menu tests, scoped mypy, and flake8 checks.
- [ ] Run `git diff --check` and inspect scoped diffs in both repositories.
- [ ] Do not commit; both repositories already contain intentional uncommitted work.
