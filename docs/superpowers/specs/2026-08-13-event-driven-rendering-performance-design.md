# Event-Driven Rendering Performance Design

## Objective

Make Tuiloom remain responsive while it displays slow synchronous streams, and
remove repeated rendering work when the visible terminal state has not changed.
The public content-source API remains compatible, including
`set_content_source(Iterator[str])`.

The implementation must preserve the project's current coding style: focused
classes, explicit private methods, strict annotations, direct control flow,
precise errors, and no unnecessary framework abstractions.

## Current Performance Problems

`ContentRenderer.update()` currently calls `next()` on streaming sources from
the UI thread. A slow producer therefore blocks rendering, keyboard input,
cursor updates, and scrolling.

Every streamed chunk is appended to one string before the complete accumulated
text is normalized again. This makes the total streaming cost grow
quadratically with the response length.

`TerminalMenu.run()` also attempts a complete render every 10 milliseconds,
even when nothing visible changed. The renderer reconstructs the menu, clips
and pads every visible viewport line, normalizes the composed frame, and only
then discovers that the frame is identical.

ANSI and Unicode processing compounds this cost because the same lines can pass
through sanitation, width calculation, clipping, padding, and visual-cell
projection several times during one frame.

## Architecture

Tuiloom will use a small internal event loop based on standard-library
primitives. It will not expose `asyncio` or require callers to change synchronous
application code.

The event loop owns all mutable UI state and all terminal writes. It wakes for:

- keyboard input;
- stream data, completion, or failure;
- dynamic-content results;
- scrolling;
- screen-context changes;
- terminal resize;
- the deadline of a pending frame.

Synchronous iterators run in a source worker outside the UI thread. The worker
publishes source events through a bounded queue and wakes the event loop through
an internal selectable channel. The UI thread drains all currently available
chunks as one batch and renders no faster than 60 frames per second.

The main data flow is:

```text
Synchronous source -> source worker -> bounded event queue
                                             |
Keyboard ------------------------------------|
Resize, scroll, context ---------------------|
                                             v
                                  UI event loop
                                             |
                                      dirty state
                                             v
                         versioned content and cached views
                                             |
                                      terminal diff
```

## Component Boundaries

### Event Loop

The event loop coordinates input, source notifications, deadlines, and render
requests. It replaces the unconditional render-and-sleep loop in
`TerminalMenu`, but `TerminalMenu` remains the public lifecycle owner.

The loop drains every immediately available input event before waiting again.
This removes the current effective limit of one buffered input event per 10
milliseconds.

### Source Worker

A source worker owns one streaming iterator or one scheduled dynamic-content
call. It produces typed internal events for data, completion, and errors. It
never writes terminal state or mutates renderer state.

The queue between the worker and event loop is bounded. A producer that runs
faster than rendering therefore experiences backpressure instead of consuming
unbounded memory.

### Content Renderer

`ContentRenderer` remains responsible for validating and normalizing content.
It gains a monotonically increasing revision that changes only when the
rendered content changes.

Streaming normalization becomes incremental. The renderer retains normalized
completed lines, the raw tail of the current line, incomplete ANSI input, the
active SGR state, and line display widths. A new batch only reprocesses the
mutable tail and newly appended lines.

The mutable tail is necessary because chunk boundaries may divide an ANSI
sequence, combining character, grapheme cluster, or emoji sequence. A line is
committed only after a newline or stream completion establishes its boundary.

### Menu Renderer

`MenuRenderer` keeps a snapshot of the `ScreenContext` values that affect its
output. It reuses its cached rendering while the snapshot remains equal.
Commands are represented in the snapshot by the keys and labels that affect
display rather than by callback identity.

Direct mutation of the public `ScreenContext` remains supported. The event loop
periodically performs a cheap snapshot comparison, but this comparison does not
trigger frame composition when the state is unchanged.

### Viewport

The viewport caches its visible lines under this key:

```text
(content_revision, width, height, offset_x, offset_y)
```

It recomputes clipping and padding only when one of these values changes.
Scrolling invalidates the viewport without invalidating normalized content or
the menu.

### Terminal Renderer

`TerminalRenderer` composes a frame only when visible state is dirty or the
terminal dimensions change. It retains the current segment-differential output
strategy.

Terminal writer boundaries continue to sanitize text. This defense is not
removed as a performance shortcut. Internally normalized values are reused so
the common rendering path avoids repeatedly processing complete unchanged
lines.

## Source Lifecycle

Static `str` and `list[str]` sources are normalized immediately without a
worker. An `Iterator[str]` is consumed continuously by a worker. A dynamic
`Callable[[], str | list[str]]` is scheduled at the rendering cadence with no
more than one call in flight at once.

Every installed content source receives an internal generation identifier.
Replacing a source performs these steps:

1. signal cancellation to the previous source;
2. assign a new generation identifier;
3. discard late events tagged with the previous identifier;
4. close the old iterator when any currently blocked `next()` returns;
5. install and render the new source independently.

A worker blocked inside external source code is never joined indefinitely
during shutdown. It is cancelled logically, future results are ignored, and it
finishes when the external call returns. Worker threads must not prevent process
shutdown.

## Frame Scheduling

Rendering is capped at 60 frames per second. Source chunks arriving before the
next deadline are combined into one update. Input, scrolling, and source events
mark only their affected state dirty.

A resize or explicit full invalidation requests an immediate complete frame.
At rest, the event loop waits and performs no viewport or frame reconstruction.
A lightweight periodic snapshot check preserves direct `ScreenContext`
mutation and provides a resize fallback where native resize notification is not
available.

## Error Handling

Worker exceptions retain their traceback and are transported to the UI thread.
The UI thread raises the failure from its event loop. The existing
`TerminalApp.run()` cleanup then restores terminal state through its `finally`
block.

This preserves the current policy that a failing content source terminates the
application. Errors are neither rendered as content nor silently discarded.
Errors from stale, replaced sources are ignored after their generation has been
cancelled.

Invalid chunk types retain precise `TypeError` reporting. Internal impossible
states retain explicit `RuntimeError` reporting in the style of the existing
renderers.

## Testing Strategy

Tests use controlled clocks, selectable wakeups, and synchronization events
instead of timing-dependent sleeps wherever possible.

Required behavior coverage includes:

- a blocked iterator does not block keyboard processing;
- multiple queued chunks form one content batch;
- rendering does not exceed 60 frames per second;
- unchanged state composes neither menu nor viewport;
- replacing a source discards stale output and closes it when possible;
- source completion, cancellation, and failure follow the defined lifecycle;
- worker exceptions are raised in the UI thread;
- split ANSI sequences remain valid and safe;
- split combining characters and emoji remain intact;
- only the mutable tail and new lines are normalized;
- buffered keyboard events are drained without a fixed per-character delay;
- terminal state is restored after asynchronous source failure.

Existing tests remain the compatibility contract for static, dynamic, and
streaming content, menu behavior, Unicode geometry, ANSI safety, segment diffs,
and terminal cleanup.

A reproducible performance benchmark lives outside the normal correctness test
suite so machine-speed variance cannot make tests flaky.

## Success Criteria

- The UI thread never calls `next()` on a streaming content source.
- Visible input latency is at most one scheduled frame, about 16.7 milliseconds
  at 60 FPS, excluding hostile external code that monopolizes the Python GIL.
- Unchanged visual state performs no complete frame composition.
- Streaming normalization has amortized linear cost in the total appended text.
- The producer-to-UI queue has a fixed memory bound.
- Existing public APIs remain compatible.
- No external runtime dependency is added.
- All current and new tests pass under strict typing and linting.

## Scope

This work changes Tuiloom only. It does not optimize model inference,
tokenization, constrained decoding, or application logic in Call-Me-Maybe.

It also does not expose a public asynchronous API, add a general task scheduler,
or turn Tuiloom into an application framework. Those would be separate design
decisions if future use cases require them.
