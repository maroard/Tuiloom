# Navigable Background Output Tasks

## Goal

Allow a menu to start a blocking operation whose captured output remains
associated with that menu while the user continues navigating through the
application. The operation must survive the originating menu being closed and
reopened.

For Call-Me-Maybe, a Hugging Face model download appears only in `ModelMenu`.
Other menus remain usable and never display that output. When the operation
finishes, its captured output is removed and the final success or error message
becomes the only task-related feedback.

## Ownership

`TerminalApp` owns background output tasks because its lifetime contains every
menu run. A task started by a menu therefore does not depend on that menu's
temporary `EventLoop` or `ContentRenderer` continuing to exist.

Each task session records:

- the originating `TerminalMenu`;
- the blocking action and its completion callbacks;
- the normalized output accumulated from standard output and standard error;
- whether the task is running, succeeded, or failed;
- its return value or exception once complete.

Only one captured-output task may be active application-wide. The output router
cannot reliably attribute writes from third-party child threads to multiple
simultaneous tasks. Ordinary iterator sources, including Call-Me-Maybe function
call generation, remain independent and may run at the same time.

## Background execution

`TerminalApp` starts the action in a daemon worker thread. The application-wide
`OutputCapture` continues to route writes made outside the UI thread into the
active task session. This includes Hugging Face and `tqdm` progress output sent
to standard error.

Tuiloom's worker never mutates menu state and never invokes completion
callbacks. It only appends output to the session and publishes an outcome. This
keeps framework-controlled UI mutations on the terminal UI thread; task actions
remain responsible for avoiding unsafe shared-state mutations.

Every active menu event loop periodically asks `TerminalApp` to dispatch
completed task outcomes. Consequently, a model download can complete while the
user is in `MainMenu`, `OptionsMenu`, or `ConfigurationMenu`; the callback is
still applied promptly by whichever menu event loop currently owns the UI
thread.

## Menu presentation

`TerminalMenu.run_with_output()` delegates execution to `TerminalApp` and
associates the returned task session with the originating menu.

While that menu is active, its event loop reads the session's accumulated
output and refreshes the content renderer when the session changes. The output
uses the existing streaming normalization rules, including carriage-return
line replacement used by progress bars.

When another menu is active, the task continues accumulating output but does
not replace that menu's content. Reopening the originating menu attaches it to
the same existing session instead of starting the action again, so all progress
accumulated while away is immediately visible.

Navigation, command entry, and scrolling remain enabled while the task runs.
Calling `run_with_output()` anywhere in the application before the current
captured-output task completes raises a clear `RuntimeError`.

## Completion

The application dispatches completion in this order on the UI thread:

1. mark the task session complete;
2. detach the session output from its originating menu;
3. restore the menu's ordinary content state and auto-scroll policy;
4. invoke `on_success(result)` or `on_error(error)`;
5. request a redraw if the originating menu is currently visible.

Detaching before the callback guarantees that the callback's final message is
not overwritten by a stale progress update.

For Call-Me-Maybe, success updates the active model and the `ModelMenu` model
label, clears the captured download output, and displays only `Model updated.`.
Failure keeps the previous model and pipeline, clears the captured output,
restores model-name input mode, and displays the existing concise error.

## Navigation and application safety

The old model remains usable while a candidate model downloads and initializes.
Generation or configuration actions performed in other menus therefore operate
on the last successfully installed application state. The candidate replaces
that state only inside the success callback.

Closing one menu must never cancel an application-owned task. Exiting the whole
terminal application may stop observing daemon workers; Tuiloom does not
promise cancellation of arbitrary blocking third-party calls.

## Tests

Tuiloom tests cover:

- navigation input remaining enabled during a task;
- a task surviving closure and reopening of its originating menu;
- output being visible only in the originating menu;
- completion callbacks running on the UI thread through another active menu;
- captured output being detached on both success and failure;
- prevention of concurrent captured-output tasks in one application;
- carriage-return progress output remaining normalized.

Call-Me-Maybe tests cover:

- navigation remaining available during model loading;
- the old model remaining active until success;
- successful completion leaving no download content and only
  `Model updated.`;
- failure clearing download content, preserving the old model, and restoring
  model-name input mode.
