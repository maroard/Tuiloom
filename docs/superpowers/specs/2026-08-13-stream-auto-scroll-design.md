# Stream Auto-Scroll Design

## Objective

Allow each `TerminalMenu` to follow content produced by an `Iterator[str]`
while preserving manual navigation when the application chooses it.

The feature keeps existing behavior by default and supports two policies:

- `"smart"` follows new stream content until the user scrolls upward;
- `"strict"` returns to the bottom whenever a new stream batch arrives.

## Public API

Tuiloom exposes this public type:

```python
type AutoScrollMode = Literal["smart", "strict"]
```

`TerminalMenu` accepts the optional constructor argument:

```python
auto_scroll: AutoScrollMode | None = None
```

The mode is also a mutable public attribute:

```python
menu.auto_scroll = "smart"
menu.auto_scroll = "strict"
menu.auto_scroll = None
```

`None` remains the default and preserves the current behavior. Invalid
constructor values raise `ValueError`. Runtime assignments are validated before
the mode is used so an invalid public-attribute mutation also fails with a clear
`ValueError` rather than producing undefined scrolling behavior.

`AutoScrollMode` is exported from `tuiloom` for annotations used by consumers.

## Behavior

Auto-scroll applies only when the active content source is an `Iterator[str]`.
It does not affect static strings, static line lists, or dynamic callables.
Horizontal scrolling remains independent in every mode.

### Disabled

When `auto_scroll` is `None`, incoming chunks never change the viewport's
vertical offset. This is exactly the current behavior.

### Smart

Smart mode follows the bottom after each incoming stream batch while following
is active.

If the user scrolls upward and the viewport moves away from its bottom boundary,
following becomes suspended. Later batches preserve that manual position. If
the user scrolls down until the viewport reaches the bottom boundary, following
becomes active again.

A scroll command that cannot move the viewport does not suspend following. In
particular, pressing Up before the content is tall enough to scroll does not
prevent future following.

### Strict

Strict mode moves to the current bottom after every incoming stream batch.
Manual upward scrolling remains possible between batches, but the next batch
returns the viewport to the bottom.

### Source and Mode Changes

Installing a new content source resets smart-mode suspension. A new iterator
therefore starts in the following state.

Changing the public mode at runtime has these effects:

- changing to `None` stops automatic movement immediately;
- changing to `"smart"` starts in the following state;
- changing to `"strict"` applies strict behavior on the next stream batch.

Switching modes does not move the viewport until a stream batch arrives. Static
or dynamic source updates never trigger a later deferred auto-scroll.

## Component Responsibilities

### TerminalMenu

`TerminalMenu` owns the public mode and validates supported values. It notifies
the terminal renderer about manual vertical navigation so smart following can
be suspended or resumed.

### EventLoop

After applying a nonempty iterator batch, `EventLoop` asks the terminal renderer
to apply the menu's current auto-scroll mode. It performs this before requesting
the next frame, ensuring the content revision and bottom boundary already
reflect the new batch.

Installing any new source resets the renderer's smart-follow state. The event
loop does not auto-scroll dynamic or static content.

### TerminalRenderer

`TerminalRenderer` owns the transient smart-follow state because it already
coordinates the active viewport and manual scroll operations. It exposes
focused internal methods for:

- resetting following after source replacement or mode transition;
- applying one stream-batch auto-scroll policy;
- detecting whether an upward scroll actually left the bottom;
- detecting whether a downward scroll returned to the bottom.

### Viewport

`Viewport` owns vertical geometry. It adds explicit operations to identify and
reach the bottom boundary:

```python
def is_at_bottom(self) -> bool:
    """Return whether the vertical offset is at its current lower boundary."""

def scroll_to_bottom(self) -> None:
    """Move the vertical offset to its current lower boundary."""
```

These methods calculate the boundary from the latest content height and
viewport height. They do not alter horizontal offset.

## Rendering and Resize Interaction

The existing terminal-render key already includes viewport offsets and content
revision. Moving to the bottom therefore invalidates the cached frame naturally.

Terminal resizing changes the viewport height during composition. On the next
stream batch, auto-scroll uses the latest viewport geometry. Resize by itself
does not override a manual smart-mode suspension.

If a batch arrives before the first viewport has been created, the requested
follow is retained and applied during frame composition after the viewport
dimensions become known.

## Error Handling

Only `None`, `"smart"`, and `"strict"` are accepted. Invalid values raise:

```text
Auto-scroll mode must be 'smart', 'strict', or None, got <value>
```

No worker, stream, or terminal exception is swallowed by auto-scroll logic.

## Testing

Required coverage includes:

- constructor and public attribute default to `None`;
- `AutoScrollMode` is part of the supported public API;
- invalid constructor and runtime values raise `ValueError`;
- disabled mode preserves the vertical offset after a stream batch;
- smart mode follows the bottom while active;
- a successful upward scroll suspends smart following;
- an ineffective upward scroll does not suspend smart following;
- reaching the bottom manually resumes smart following;
- strict mode returns to the bottom on every later batch;
- a new iterator resets smart suspension;
- static and dynamic updates do not auto-scroll;
- horizontal offsets are unchanged by auto-scroll;
- a batch received before first composition follows the bottom once the
  viewport exists;
- resize behavior and terminal-too-small rendering remain unchanged.

## Scope

This feature does not add page-wise scrolling, configurable margins, animated
scrolling, mouse-wheel handling, or automatic horizontal following. Those are
separate interaction features.
