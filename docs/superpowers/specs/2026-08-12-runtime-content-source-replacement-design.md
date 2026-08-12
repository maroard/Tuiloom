# Runtime Content Source Replacement Design

## Goal

Allow a running Tuiloom menu to replace its content source immediately, then
use that behavior in Call-Me-Maybe to stream every configured prompt through a
single content source.

## Root Cause

`TerminalMenu.set_content_source()` currently replaces only
`TerminalMenu._content_source`. A running menu has already created a
`ContentRenderer`, and `TerminalRenderer` retains that object. Consequently,
the active renderer continues updating the old source.

Call-Me-Maybe also creates one lazy generator per prompt and installs them in a
synchronous loop. No render occurs during that callback, so every generator is
replaced before consumption and only the last one remains stored.

## Tuiloom Design

`TerminalMenu.set_content_source()` remains the public entry point. It always
stores the source for future runs. When a terminal renderer is active, it also
creates one new `ContentRenderer`, stores that renderer on the menu, gives the
same object to `TerminalRenderer`, and invalidates the cached terminal frame.

`TerminalRenderer` will expose a focused `set_content_renderer()` method. This
keeps terminal-renderer ownership changes inside the renderer and provides a
single place to reset viewport state. The viewport will be cleared when the
content renderer changes so offsets and dimensions from the previous source do
not leak into the new source.

Calling `set_content_source()` before `run()` continues to only store the
source. Calling it during a command takes effect on the next loop render.

## Call-Me-Maybe Design

The generate command will install one generator. That generator iterates over
all prompts, builds each instruction string only when reached, yields a visible
prompt heading, delegates generation with `yield from decoder.stream(...)`, and
yields spacing before the next prompt.

The command callback therefore returns immediately after installing the source.
Tuiloom drives generation lazily with one `next()` call per render update, and
all prompts remain part of one accumulated stream instead of replacing each
other.

## Error Behavior

Exceptions raised while creating a content renderer still propagate from
`set_content_source()`. Exceptions raised later by Call-Me-Maybe's generator
propagate from the render loop and continue through the existing application
cleanup and top-level error handling. `ConstrainedDecoder.stream()` retains its
`finally` reset behavior between prompts.

## Testing

Tuiloom tests will verify that:

- a source set before a menu run remains stored without requiring active
  renderer objects;
- a source set during a run replaces both renderer references with the same
  `ContentRenderer`;
- the new streaming source is consumed on the next render update;
- the viewport and frame cache are invalidated when the source changes.

Call-Me-Maybe tests will verify that:

- the command installs exactly one iterator;
- no decoder stream is consumed inside the command callback;
- consuming that iterator streams every prompt in order;
- headings and separators are included without losing generated fragments.

## Scope Limits

This change does not introduce background threads, asynchronous generation,
stream cancellation, configurable update rates, or segment-level terminal
diffs. One generator step may still block the UI while the model computes its
next fragment.
