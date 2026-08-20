# Captured Output Tasks Design

## Goal

Allow a running `TerminalMenu` to execute a blocking callable outside the UI
thread while displaying its standard output and standard error as the menu's
active streaming content source. The completed output remains visible.

The first consumer is Call-Me-Maybe's Hugging Face model loading flow, but the
API and implementation remain independent of Hugging Face.

## Public API

`TerminalMenu` exposes:

```python
menu.run_with_output(
    action,
    on_success=handle_result,
    on_error=handle_error,
)
```

`action` is a synchronous zero-argument callable. Tuiloom executes it in the
existing source worker infrastructure. `on_success(result)` or
`on_error(exception)` runs later in the event-loop thread, where it may safely
update menu state. Only one captured-output task may run in an application at a
time.

Starting the task replaces the current content source with its captured output
and enables strict stream following. The captured content is not restored or
cleared when the task completes.

## Output routing

Tuiloom temporarily installs standard-stream routers for the duration of
`TerminalApp.run()`. Writes from the UI thread continue to the original
terminal streams. While a captured task is active, writes from its worker and
child worker threads are routed to the task's source-event queue. This captures
both ordinary `print()` calls and progress libraries such as `tqdm`, including
Hugging Face's parallel download workers, without capturing Tuiloom's own
screen rendering.

The routers preserve the common text-stream surface used by third-party
libraries, including `write`, `flush`, `isatty`, `fileno`, and `encoding`.
Installation is always reversed when the application exits.

## Events and lifecycle

A captured task is a dedicated internal source type. `SourceWorker` executes
its callable while output routing is active, publishes output as ordinary data
events, and publishes either a task-success result or a task-error exception.
It completes the stream before publishing the task outcome. This lets the menu
freeze the captured output and lets callbacks safely replace the content source
without a stale completion event reaching the new renderer.

`EventLoop` applies output batches first and dispatches task completion in its
own thread. Task errors are delivered to `on_error`; ordinary iterator-source
errors retain their existing propagation behavior. Exceptions raised by either
completion callback propagate normally rather than being hidden.

While a task is active, character input, Enter, Backspace, and Escape are
ignored. Arrow-key scrolling remains available so the user can inspect the
journal. Tuiloom does not claim to cancel arbitrary Python callables.

## Progress-line rendering

Streaming content treats a bare carriage return (`\r`) as replacement of the
current unfinished line. A CRLF sequence remains a newline. This matches how
`tqdm` redraws a progress bar and prevents every percentage update from being
concatenated or retained as a separate line.

## Call-Me-Maybe integration

`ModelMenu` exits text-input mode, displays a loading message, and schedules
the existing transactional model-update callback with `run_with_output`.

- On success, it installs the returned candidate, updates the displayed model
  name, and reports `Model updated.`.
- On an expected loading error, it restores model-name input mode, keeps the
  previous model, and displays the existing concise error.
- On an unexpected programming exception, it re-raises in the UI thread.

The Hugging Face download log remains the menu's content after either outcome.

## Verification

Tuiloom tests cover stream routing without real terminal writes, worker result
and error delivery, UI-thread callbacks, busy input behavior, CR progress-line
replacement, public documentation, and stream restoration on application exit.
Call-Me-Maybe tests cover asynchronous scheduling plus successful and failed
transactional model updates without downloading a real model.
