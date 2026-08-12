# Line Differential Rendering Design

## Goal

Replace the unconditional full-screen redraw with a line-based differential
render while keeping the existing renderer structure and writing style. The
command input must remain visible after the prompt, and the design must leave a
clear extension point for a future segment-based line diff.

## Current Problem

`TerminalMenu.run()` renders every 10 milliseconds. `TerminalRenderer.render()`
clears and rewrites the complete screen on every call, even when nothing has
changed. At the same time, `TerminalMenu._input_buffer` is not included in the
rendered frame and the application cursor is hidden. This causes visible
flicker and makes typed commands invisible.

## Design

`TerminalMenu` will continue to own the command buffer and event handling. It
will pass the current input buffer to `TerminalRenderer.render()`.

`TerminalRenderer` will keep composing a complete logical frame from the
content viewport and menu. The prompt and command buffer will form the final
line of that frame. The renderer will store the previously displayed lines and
the previous terminal size.

Before writing, the renderer will compare the previous and current frames. A
small private diff unit will describe which complete lines must be replaced.
The terminal-writing unit will apply those replacements with ANSI cursor
movement and line-erasure sequences. Keeping comparison and terminal output
separate provides the future extension point: the line replacement description
can later be replaced or supplemented by segment replacements without changing
frame composition.

The first frame, a terminal resize, and exceptional states such as a terminal
that is too small will invalidate the cached frame and use a complete redraw.
If the new frame is shorter, obsolete trailing lines will be explicitly
cleared.

After each render, the terminal cursor will be positioned immediately after the
prompt and current input. It will be visible while waiting for input and hidden
only while a changed frame is being written, preventing cursor movement from
being exposed to the user.

## Components

### `TerminalMenu`

- Retains the existing polling loop and 10 millisecond input responsiveness.
- Passes `_input_buffer` into the renderer.
- Keeps character, backspace, Enter, scrolling, and Escape behavior unchanged.

### `TerminalRenderer`

- Keeps ownership of viewport composition and terminal output.
- Composes the prompt and input buffer as part of the logical frame.
- Caches the last displayed frame and terminal dimensions.
- Chooses between a full redraw and line replacements.
- Restores the visible cursor to the input position after output.

### Diff representation

- Represents replacements independently from ANSI output.
- Initially identifies complete changed lines.
- Allows a later implementation to represent changed column ranges on a line
  without changing menu or content rendering.

## Rendering Rules

1. An unchanged frame produces no terminal write.
2. A changed existing line is erased and rewritten in place.
3. A newly added line is written at its new row.
4. A removed trailing line is erased.
5. A resize or invalid cache causes a complete redraw.
6. The cache is updated only after the frame has been written successfully.
7. The cursor finishes immediately after the visible input buffer.

## Testing

Tests will be written before production changes and will verify:

- the input buffer is included after the prompt;
- a character and backspace produce the expected frame changes;
- an unchanged frame produces no output;
- only changed lines are rewritten;
- removed trailing lines are cleared;
- resizing forces a complete redraw;
- the final cursor position follows the prompt and input;
- existing content, viewport, command dispatch, lint, and type checks remain
  green.

Terminal writes and terminal dimensions will be isolated at their existing
module boundary so the differential behavior can be tested without requiring
an interactive terminal.

## Scope Limits

This iteration will not implement character-cell or segment-level diffs,
Unicode display-width calculation, ANSI-aware string width, or a configurable
frame rate. It will preserve the existing content-source update cadence and
public API except for making typed input visibly part of the terminal display.
