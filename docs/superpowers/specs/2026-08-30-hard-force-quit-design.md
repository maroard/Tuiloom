# Hard Force Quit Design

## Problem

Tuiloom currently implements **Force quit** as cooperative cancellation. It
marks active work as cancelled, discards future output and callbacks, and then
waits for every worker thread to terminate. A worker blocked in network or
native code cannot necessarily observe cancellation. In that case the
application remains indefinitely on `Stopping operation...`.

Call-Me-Maybe exposes this failure while Transformers downloads or loads a
model with `from_pretrained()`. The current behavior contradicts the label
**Force quit**, which must guarantee that control returns to the shell.

## Chosen Behavior

Selecting **Force quit** requests an immediate, process-wide hard exit. Tuiloom
must not wait for active output tasks, iterator sources, dynamic sources, or
native-backed work to terminate.

Before terminating the process, Tuiloom performs only bounded cleanup:

- stop the menu and event loop without joining workers;
- close Tuiloom-owned input and selector resources when closing them cannot
  wait for application work;
- restore the cursor, mouse modes, alternate screen, stdout, and stderr;
- terminate the process through `os._exit()`.

The hard-exit path is silent and returns a non-zero process status. It does not
render `Stopping operation...`, run task callbacks, or attempt further frames.
It may interrupt application writes or leave third-party cache files for the
third-party library to resume or clean up later. This is intentional for a
forceful exit.

## Normal Shutdown

**Wait and quit** retains the existing safe behavior: active work may finish,
callbacks may run, workers are joined, and all normal cleanup completes.

Cancelling the exit menu also retains the existing behavior and returns to the
application. Ordinary shutdown with no active operation is unchanged.

## Control Flow

The menu records a hard-exit request as soon as **Force quit** is activated and
stops its UI loop immediately. Cleanup code checks this state and selects a
non-joining event-loop close path. The request then propagates to
`TerminalApp.run()`, whose finalization restores terminal state before invoking
the process terminator.

The process terminator is kept behind a small internal boundary so unit tests
can replace it without killing the test runner. Production continues to use
`os._exit()` so non-daemon threads and blocked native calls cannot delay exit.

## Error Handling

Terminal restoration is attempted even when another exception is already in
flight. Once a hard exit has been requested, callbacks and errors from active
work are abandoned because the process is about to terminate.

Cleanup on the hard-exit path must never call an unbounded worker `join()`.
Normal cleanup keeps the stronger resource-safety guarantees already provided
by Tuiloom.

## Verification

Automated tests will prove that:

- activating **Force quit** stops the menu immediately instead of entering the
  `stopping` view;
- a permanently alive fake operation cannot delay the hard-exit path;
- event-loop hard cleanup cancels work but does not join it;
- input and terminal restoration happen before the process terminator;
- active output task callbacks are not invoked;
- **Wait and quit**, exit cancellation, and ordinary shutdown retain their
  existing behavior;
- a subprocess/PTY integration test observes a clean terminal and prompt-facing
  exit even while a background operation remains blocked.

