# Multi-content panels and task-exit menu design

## Goal

Replace the root task-exit footer prompt with a normal keyboard-navigable menu
and generalize menu content from one source to an ordered collection of
independently focusable panels.

The first layout is a vertical stack. The data model must leave room for other
layouts later without exposing renderer internals in the public API.

## Public API

Introduce an exported `ContentPanel` handle. Applications obtain handles from
the owning menu rather than constructing them directly:

```python
logs = menu.add_content_panel(
    log_stream,
    description="Downloading",
    auto_scroll="strict",
)
metrics = menu.add_content_panel(
    get_metrics,
    description="Indexing",
)

logs.set_source(new_log_stream)
logs.set_description("Downloading model")
logs.set_auto_scroll("smart")
metrics.move(0)
metrics.remove()
```

`TerminalMenu` exposes an immutable ordered view and creates panels:

```python
menu.content_panels -> tuple[ContentPanel, ...]

menu.add_content_panel(
    content_source,
    *,
    description="Content in progress",
    auto_scroll=None,
    position=None,
) -> ContentPanel
```

`ContentPanel` owns the explicit mutation API:

```python
panel.set_source(content_source) -> None
panel.set_description(description) -> None
panel.set_auto_scroll(mode) -> None
panel.move(position) -> None
panel.remove() -> None
```

It also has read-only `description`, `position`, and `auto_scroll` properties.
Its identity remains stable when its source, description, scroll mode, or
position changes. Mutation methods delegate lifecycle and ordering changes to
the owning menu and reject a removed handle.

There are deliberately no `TerminalMenu.add_content_source()`,
`set_content_panel_*()`, `move_content_panel()`, or `remove_content_panel()`
aliases. This avoids two public ways to perform the same panel operation. The
names and ownership model were approved at the required API review checkpoint.

## Backward compatibility

The `content_source` constructor argument creates the primary panel. An
inherited `global_content_source` does the same. Existing
`set_content_source()` replaces the primary panel, or creates it when no primary
panel remains. Existing `menu.auto_scroll` reads or updates the primary panel's
mode.

A menu with one source renders as it does today, including its unlabeled outer
content border during ordinary navigation. A menu with no panels keeps the
existing no-content behavior and automatic message.

`run_with_output()` creates a temporary panel for captured output and removes
it after completion. Other panels remain visible. Captured output remains
limited to one simultaneous task per application; supporting concurrent global
stdout captures is outside this change.

The exported `MessageKey.TASK_EXIT_CHOICES`, `TASK_WAITING`, and
`TASK_STOPPING` members remain available for compatibility but no longer drive
the automatic task-exit interface. They will be documented as obsolete only
after the API review checkpoint.

## Panel rendering and focus

Each panel is a separate bordered content box. Its description labels the box
when multiple panels are visible or while the task-exit view is active. The
ordinary single-panel view remains unlabeled for compatibility. Panels are
stacked vertically above the menu and retain the full terminal width. The
available content height is divided equally; remainder rows are assigned in
panel order. Each panel must receive at least one inner content row. If the menu
and all panel borders plus their minimum content do not fit, the existing
terminal-too-small state is rendered.

Each panel owns an independent viewport and auto-scroll state. The existing
focus action cycles through all focusable objects:

```text
menu -> panel 1 -> panel 2 -> ... -> menu
```

When the menu has focus, directional actions navigate commands. When a panel
has focus, directional actions scroll only that panel. Removing the focused
panel advances focus to the next surviving focusable object.

## Runtime model

The event loop owns one internal runtime per panel. A runtime groups the
panel's `ContentRenderer`, optional `SourceWorker`, source generation, dynamic
evaluation state, viewport, and auto-scroll state.

Workers publish through a shared bounded queue. Every `SourceEvent` identifies
both its panel and source generation. The event loop batches events per panel,
applies data to the corresponding renderer, and ignores stale events only for
the replaced generation.

While a menu is running:

- Adding a panel with `add_content_panel()` starts its worker immediately when
  the source is non-static.
- Replacing a source requests cooperative cancellation of the old worker,
  retains its last render, and installs the replacement only after the old
  worker really terminates.
- Removing a panel hides it immediately from ordinary navigation, requests
  cancellation, and tracks its retiring runtime until termination. If the user
  requests root exit before it terminates, its last render and description are
  included in the task-exit view because it still blocks safe shutdown.
- Moving or relabeling a panel does not restart its source.
- Closing the event loop cancels and joins every live or detached worker before
  restoring terminal resources.

A completed source keeps its last content but no longer counts as an active
operation. For compatibility, a dynamic callable counts as active only while
one of its evaluations is in flight; remaining installed between evaluations
does not block exit. The producer and output-consumer worker used by
`run_with_output()` belong to one logical panel and count as one operation.

If a source raises, the first error is propagated with its traceback after all
other workers have been cancelled and joined.

## Task-exit menu

When Quit/Back is requested from the root menu while one or more logical
operations are active, `TerminalMenu` enters a temporary internal exit view.
It does not push a user-visible submenu or create another event loop.

The initial view:

- focuses `Force quit`;
- uses `Operation in progress` or `Operations in progress` as its title;
- displays only runtimes associated with active operations, including a
  retiring removed panel whose worker has not terminated;
- offers `Force quit`, `Wait and quit`, and `Cancel` as ordinary selectable
  rows;
- accepts the configured navigation, activation, focus, and back actions;
- does not accept the former `1`, `2`, and `0` shortcuts;
- treats the back action as `Cancel`.

`Cancel` restores the original title, footer message, focus, and selection
without changing active work.

`Wait and quit` keeps the exit view and leaves `Cancel` as its only selectable
row. Operation descriptions animate while waiting. Cancelling this state
returns to the original menu and clears any output-task exit-on-completion
registration.

`Force quit` requests cooperative cancellation, discards future captured
output and callbacks as today, and changes the title to `Stopping operation...`
or `Stopping operations...`. This state is non-interactive and retains each
operation's last visible output until the underlying work really terminates.

The operation list is live in every exit state, including the initial
three-choice view. Completed panels disappear immediately and the title updates
between singular and plural. Operations started while the view is open are
included. When the final operation completes, the original quit request is
fulfilled automatically, even if the user had not yet selected an exit mode.

The exit view never writes its title or status into `ScreenContext.title` or
`ScreenContext.message`; the renderer derives the temporary visible state.

## Verification

Unit and integration coverage must include:

- panel creation, ordering, mutation, removal, and ownership validation;
- simultaneous routing for multiple streaming and dynamic sources;
- per-panel stale-generation filtering and independent refresh scheduling;
- cancellation and joining on replacement, removal, close, and source error;
- equal-height vertical layout, remainder allocation, resizing, and the
  terminal-too-small boundary;
- focus cycling, focused-panel scrolling, and independent auto-scroll;
- unchanged single-source behavior;
- arrow/activation/back-only exit-menu input and rejection of numeric choices;
- live panel removal, singular/plural updates, and automatic quit at zero;
- wait, force, and cancel flows with multiple workers;
- a PTY-level assertion over the actual multi-panel terminal frame.

## Documentation and API review checkpoint

Implementation proceeds test-first. After the public API and its tests work,
but before editing the README, present the user with:

- the final exported class and method signatures;
- a concise multi-source example;
- compatibility behavior for `set_content_source()`, `auto_scroll`, and
  `run_with_output()`;
- any naming or behavior that changed during implementation.

README work is blocked until the user explicitly approves that API review.
After approval, update the guide, API reference, exit semantics, message-key
status, and limitations.
