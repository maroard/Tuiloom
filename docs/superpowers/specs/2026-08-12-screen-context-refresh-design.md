# Screen Context Refresh Design

## Goal

Keep an active menu renderer synchronized with every display field of its
`ScreenContext`. A command must be able to change a message, text, alert,
prompt, command collection, column layout, title, application name, or width
and have that change appear on the next terminal frame.

## Cause

`MenuRenderer` currently copies the `ScreenContext` fields only during its
construction. Commands later mutate the context owned by `TerminalMenu`, but
the active renderer continues to render its initial copies. Invalidating the
terminal frame cache forces a redraw of that stale state and therefore cannot
make the new value visible.

## Design

`MenuRenderer` will expose an explicit
`update_screen_context(screen_context)` method. The method will copy all
display fields used by the renderer and resolve its width:

- an explicit context width is used as-is;
- an automatic width (`None`) is recalculated from the newly copied state.

The constructor will call this method so initialization and later updates use
one code path.

Immediately before composing each frame, `TerminalMenu._render()` will pass
its current `screen_context` to the active `MenuRenderer`. It will then call
`TerminalRenderer.render()` normally. This makes the synchronization boundary
visible in the menu loop and keeps `MenuRenderer.render()` limited to
formatting its current state.

## Rendering Flow

1. Application or command mutates `TerminalMenu.screen_context`.
2. The next loop iteration enters `TerminalMenu._render()`.
3. `MenuRenderer.update_screen_context()` copies the complete current state.
4. `TerminalRenderer` composes a new logical frame.
5. Existing line-differential rendering writes only changed terminal lines.

No full redraw is required solely because the context changed. Existing
explicit invalidation after a command remains valid and unchanged.

## Scope

The change is internal to Tuiloom and does not alter Call-Me-Maybe or the
public package exports. It does not introduce observers, callbacks, dirty
flags, or field-specific setters.

## Tests

Tests will prove that:

- a message changed after renderer construction appears after synchronization;
- all other display fields are refreshed, including a replaced command map;
- automatic width is recalculated from the new state;
- explicit width remains the value supplied by the current context;
- `TerminalMenu._render()` synchronizes before delegating the frame render;
- the complete existing test suite still passes.
