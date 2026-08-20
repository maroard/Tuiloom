# Tuiloom

Tuiloom builds typed terminal menus whose command callbacks receive the context
of each execution.

## Commands

```python
from tuiloom import (
    CommandBehavior,
    CommandContext,
    ScreenContext,
    TerminalApp,
    TerminalMenu,
)

app = TerminalApp("Generator")
menu = TerminalMenu(
    app,
    ScreenContext("Generator", "Main Menu", "Generation"),
)
app.set_main_menu(menu)


def generate(context: CommandContext) -> None:
    context.menu.set_content_source("Generated from this menu")


menu.add_command("Generate", generate)
```

Tuiloom creates `CommandContext` during dispatch. Its `app`, `menu`, and
`command_key` fields identify the active application, the menu where the command
was entered, and the exact resolved registry key.

Command labels can change at runtime without replacing their behavior or key:

```python
menu.add_command("Connect", connect, index=1)
menu.set_command_label("1", "Disconnect")
```

`set_command_label()` raises `KeyError` when the requested key is not registered.

Application dependencies can stay in closures; no command class is required:

```python
def make_generate_command(
    decoder: ConstrainedDecoder,
    prompt_builder: PromptBuilder,
) -> CommandBehavior:
    def generate(context: CommandContext) -> None:
        instructions = prompt_builder.get_prompt()
        context.menu.set_content_source(decoder.stream(instructions))

    return generate
```

## ANSI styles and Unicode

Every visual Tuiloom string supports SGR colors and styles, including 16-color,
256-color, and true-color sequences. Layout and cursor positioning account for
combining characters, wide CJK text, and emoji grapheme clusters.

Tuiloom intentionally strips terminal control sequences that can move the
cursor, erase the screen, scroll, or change terminal state. The renderer keeps
exclusive control of terminal geometry while preserving user-provided style.

## Streaming performance

Synchronous iterators keep the same public API shown above, but Tuiloom consumes
them outside the UI thread. Generated chunks cross a bounded buffer and are
grouped into visual updates rendered at up to 60 frames per second. Keyboard
input, scrolling, and cursor updates therefore remain responsive while a source
waits for its next chunk.

Generators should release the Python GIL during long native work when possible.
A cancelled generator must eventually return from a blocked `next()` call before
Tuiloom can close that generator's own resources, although stale output is
ignored immediately.

Iterator content can follow its newest output automatically:

```python
menu.auto_scroll = "smart"   # pauses after manual upward scrolling
menu.auto_scroll = "strict"  # returns to the bottom after every batch
menu.auto_scroll = None       # disabled, the default
```

Auto-scroll is vertical and applies only to iterator-backed content.

## Blocking operations with captured output

Commands can move blocking work off the UI thread while displaying everything
it writes to standard output or standard error:

```python
def download(context: CommandContext) -> None:
    context.menu.run_with_output(
        lambda: download_model("organization/model"),
        on_success=lambda model: show_model(model),
        on_error=lambda error: show_error(error),
    )
```

The application owns the task, so leaving its originating menu does not stop
the work. Captured output is shown only in that menu and is replayed when the
user returns to it; every other menu keeps its own content and commands remain
available. Progress bars that rewrite a line with a carriage return are
rendered as one updating line.

Immediately before a completion callback runs on the UI thread, Tuiloom removes
the temporary output and restores the menu's ordinary content and auto-scroll
mode. Only one captured-output task can run per application at a time.
